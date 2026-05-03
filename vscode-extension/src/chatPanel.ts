import * as vscode from 'vscode';
import {
    AgentClient,
    PlanInfo,
    StatusResponse,
    FileChangeInfo,
    StreamEvent,
} from './agentClient';

export class ChatPanel implements vscode.WebviewViewProvider {
    public static readonly viewType = 'agentChatPanel';

    private view?: vscode.WebviewView;
    private sessionId?: string;
    private pollingInterval?: ReturnType<typeof setInterval>;
    private readonly extensionUri: vscode.Uri;
    private readonly agentClient: AgentClient;
    private readonly globalState: vscode.Memento;
    private onPendingChangesCallback?: (sessionId: string, changes: FileChangeInfo[]) => void;
    private hasStreamedTokens = false;
    private messageLog: Array<{ role: string; content: string; timestamp: string }> = [];

    constructor(extensionUri: vscode.Uri, agentClient: AgentClient, globalState: vscode.Memento) {
        this.extensionUri = extensionUri;
        this.agentClient = agentClient;
        this.globalState = globalState;

        // Restore session ID and message log from persistent storage
        this.sessionId = this.globalState.get<string>('sessionId');
        this.messageLog = this.globalState.get<Array<{ role: string; content: string; timestamp: string }>>('messageLog', []);
    }

    public onPendingChanges(callback: (sessionId: string, changes: FileChangeInfo[]) => void): void {
        this.onPendingChangesCallback = callback;
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ): void {
        this.view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };

        webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(
            async (message: { type: string; text?: string }) => {
                if (message.type === 'sendMessage' && message.text) {
                    await this.sendMessage(message.text);
                } else if (message.type === 'clearChat') {
                    this.clearSession();
                } else if (message.type === 'webviewReady') {
                    // Webview has loaded — restore previous messages
                    this.restoreMessages();
                }
            }
        );

        webviewView.onDidDispose(() => {
            this.stopStatusPolling();
        });
    }

    public show(): void {
        if (this.view) {
            this.view.show?.(true);
        }
    }

    /**
     * Clear the current session and start fresh.
     */
    public clearSession(): void {
        this.sessionId = undefined;
        this.messageLog = [];
        this.hasStreamedTokens = false;
        void this.globalState.update('sessionId', undefined);
        void this.globalState.update('messageLog', []);
        this.postMessageToWebview({ type: 'clearMessages' });
    }

    public async sendMessage(text: string): Promise<void> {
        // Handle /clear command
        if (text.trim().toLowerCase() === '/clear' || text.trim().toLowerCase() === 'clear') {
            this.clearSession();
            this.addMessage('system', 'Chat cleared. Starting a new session.');
            return;
        }

        this.addMessage('user', text);
        this.setTyping(true);

        try {
            const workspacePath = this.getWorkspacePath();

            // Start a streaming agent message for real-time token display
            this.postMessageToWebview({ type: 'startStreamingMessage' });
            this.hasStreamedTokens = false;
            let streamedResponse = '';

            await this.agentClient.sendPromptStreaming(
                text,
                workspacePath,
                (evt: StreamEvent) => {
                    switch (evt.event) {
                        case 'session':
                            this.sessionId = evt.data.session_id;
                            // Persist session ID immediately
                            void this.globalState.update('sessionId', this.sessionId);
                            break;
                        case 'thinking':
                            // Agent is calling a tool — show it
                            this.setTyping(false);
                            this.postMessageToWebview({
                                type: 'streamToken',
                                token: `\n🔧 ${evt.data.message}\n`,
                            });
                            streamedResponse += `\n🔧 ${evt.data.message}\n`;
                            this.hasStreamedTokens = true;
                            break;
                        case 'tool_result':
                            // Tool returned a result — show a brief summary
                            break;
                        case 'chat_token':
                            this.setTyping(false);
                            this.postMessageToWebview({
                                type: 'streamToken',
                                token: evt.data.token,
                            });
                            streamedResponse += evt.data.token;
                            this.hasStreamedTokens = true;
                            break;
                        case 'file_change':
                            break;
                        case 'plan':
                            this.setTyping(false);
                            this.displayPlan(evt.data as PlanInfo);
                            break;
                        case 'token':
                            this.postMessageToWebview({
                                type: 'streamToken',
                                token: evt.data,
                            });
                            streamedResponse += evt.data;
                            this.hasStreamedTokens = true;
                            break;
                        case 'task_result':
                            break;
                        case 'task_error':
                            this.addMessage(
                                'system',
                                `Task ${evt.data.task_id} failed: ${evt.data.error}`
                            );
                            break;
                        case 'done':
                            this.postMessageToWebview({ type: 'endStreamingMessage' });
                            if (this.hasStreamedTokens) {
                                // Log the streamed response without re-rendering
                                this.messageLog.push({
                                    role: 'agent',
                                    content: streamedResponse,
                                    timestamp: new Date().toISOString(),
                                });
                                this.persistState();
                            } else {
                                this.addMessage('agent', 'Task execution completed.');
                            }
                            this.hasStreamedTokens = false;
                            // Fetch final status to get pending changes
                            if (this.sessionId) {
                                this.startStatusPolling(this.sessionId);
                            }
                            break;
                        case 'error':
                            this.postMessageToWebview({ type: 'endStreamingMessage' });
                            this.hasStreamedTokens = false;
                            this.addMessage(
                                'system',
                                `Error: ${evt.data.error ?? evt.data}`
                            );
                            break;
                    }
                },
                this.sessionId
            );

            this.setTyping(false);
        } catch (error) {
            this.setTyping(false);
            this.postMessageToWebview({ type: 'endStreamingMessage' });
            const errorMessage =
                error instanceof Error
                    ? error.message
                    : 'An unknown error occurred';
            this.addMessage('system', `Error: ${errorMessage}`);
        }
    }

    public addMessage(
        role: 'user' | 'agent' | 'system',
        content: string
    ): void {
        this.messageLog.push({
            role,
            content,
            timestamp: new Date().toISOString(),
        });
        this.persistState();
        this.postMessageToWebview({
            type: 'addMessage',
            role,
            content,
        });
    }

    public displayPlan(plan: PlanInfo): void {
        this.postMessageToWebview({
            type: 'showPlan',
            plan,
        });
    }

    public updateProgress(status: StatusResponse): void {
        const currentTask = status.current_task ?? '';
        this.postMessageToWebview({
            type: 'updateProgress',
            progress: status.progress,
            currentTask,
        });
    }

    public startStatusPolling(sessionId: string): void {
        this.stopStatusPolling();

        this.pollingInterval = setInterval(async () => {
            try {
                const status = await this.agentClient.getStatus(sessionId);
                this.updateProgress(status);

                if (
                    status.status === 'completed' ||
                    status.status === 'error' ||
                    status.status === 'cancelled'
                ) {
                    this.stopStatusPolling();

                    if (status.status === 'completed') {
                        this.addMessage('agent', 'Task execution completed.');
                        if (status.pending_changes.length > 0) {
                            this.notifyPendingChanges(sessionId, status.pending_changes);
                        }
                    } else if (status.status === 'error') {
                        this.addMessage(
                            'system',
                            'Task execution encountered an error.'
                        );
                    } else {
                        this.addMessage('system', 'Session was cancelled.');
                    }
                }
            } catch (_error) {
                this.stopStatusPolling();
                this.addMessage(
                    'system',
                    'Lost connection to agent server.'
                );
            }
        }, 1000);
    }

    public stopStatusPolling(): void {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = undefined;
        }
    }

    /**
     * Export the full conversation log as a formatted string.
     * Each message includes timestamp, role, and content.
     */
    public exportConversation(): string {
        if (this.messageLog.length === 0) {
            return '(no messages)';
        }
        const header = `# Agent Chat Export\n# Session: ${this.sessionId ?? 'unknown'}\n# Exported: ${new Date().toISOString()}\n`;
        const body = this.messageLog
            .map((m) => `[${m.timestamp}] ${m.role.toUpperCase()}:\n${m.content}`)
            .join('\n\n---\n\n');
        return header + '\n' + body + '\n';
    }

    /**
     * Restore previous messages into the webview after it's been recreated.
     */
    private restoreMessages(): void {
        if (this.messageLog.length === 0) {
            return;
        }
        // Send all previous messages to the webview for rendering
        this.postMessageToWebview({
            type: 'restoreMessages',
            messages: this.messageLog,
        });
    }

    /**
     * Persist session ID and message log to globalState.
     */
    private persistState(): void {
        void this.globalState.update('sessionId', this.sessionId);
        // Keep only the last 100 messages to avoid bloating storage
        const toSave = this.messageLog.slice(-100);
        void this.globalState.update('messageLog', toSave);
    }

    private setTyping(typing: boolean): void {
        this.postMessageToWebview({
            type: 'setTyping',
            typing,
        });
    }

    private notifyPendingChanges(sessionId: string, changes: FileChangeInfo[]): void {
        const fileList = changes
            .map((c) => `${c.change_type}: ${c.file_path}`)
            .join('\n');
        this.addMessage(
            'agent',
            `${changes.length} file change(s) pending review:\n${fileList}`
        );

        if (this.onPendingChangesCallback) {
            this.onPendingChangesCallback(sessionId, changes);
        }
    }

    private getWorkspacePath(): string {
        const config = vscode.workspace.getConfiguration('agent');
        const remoteWorkspacePath = config.get<string>('remoteWorkspacePath', '');
        if (remoteWorkspacePath) {
            return remoteWorkspacePath;
        }
        const folders = vscode.workspace.workspaceFolders;
        if (folders && folders.length > 0) {
            return folders[0].uri.fsPath;
        }
        return '';
    }

    private postMessageToWebview(message: Record<string, unknown>): void {
        if (this.view) {
            void this.view.webview.postMessage(message);
        }
    }

    public getHtmlForWebview(_webview: vscode.Webview): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Chat</title>
    <style>
        body {
            margin: 0;
            padding: 8px;
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            color: var(--vscode-foreground);
            background-color: var(--vscode-sideBar-background);
        }
        #messages {
            overflow-y: auto;
            margin-bottom: 8px;
        }
        .message {
            margin-bottom: 8px;
            padding: 6px 8px;
            border-radius: 4px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .message.user {
            background-color: var(--vscode-input-background);
        }
        .message.agent {
            background-color: var(--vscode-editor-background);
        }
        .message.system {
            color: var(--vscode-descriptionForeground);
            font-style: italic;
        }
        #typing-indicator {
            display: none;
            color: var(--vscode-descriptionForeground);
            font-style: italic;
            margin-bottom: 8px;
        }
        #progress-bar {
            display: none;
            margin-bottom: 8px;
        }
        #progress-bar .bar {
            height: 4px;
            background-color: var(--vscode-progressBar-background);
            border-radius: 2px;
            transition: width 0.3s;
        }
        #progress-task {
            font-size: 0.9em;
            color: var(--vscode-descriptionForeground);
            margin-top: 2px;
        }
        #toolbar {
            display: flex;
            justify-content: flex-end;
            margin-bottom: 4px;
        }
        #toolbar button {
            padding: 2px 8px;
            font-size: 0.85em;
            background: transparent;
            color: var(--vscode-descriptionForeground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 3px;
            cursor: pointer;
        }
        #toolbar button:hover {
            background-color: var(--vscode-input-background);
            color: var(--vscode-foreground);
        }
        #input-area {
            display: flex;
            gap: 4px;
        }
        #input-area input {
            flex: 1;
            padding: 6px 8px;
            background-color: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            outline: none;
            font-family: inherit;
            font-size: inherit;
        }
        #input-area button {
            padding: 6px 12px;
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        #input-area button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        pre {
            background-color: var(--vscode-editor-background);
            border-radius: 4px;
            padding: 8px;
            overflow-x: auto;
            margin: 4px 0;
        }
        pre code {
            background-color: transparent;
            padding: 0;
        }
        code {
            background-color: var(--vscode-textCodeBlock-background, rgba(127,127,127,0.15));
            padding: 1px 4px;
            border-radius: 3px;
            font-family: var(--vscode-editor-font-family, monospace);
            font-size: var(--vscode-editor-font-size, 0.9em);
        }
        .message.streaming::after {
            content: '\\25AE';
            animation: blink 0.7s step-end infinite;
        }
        @keyframes blink {
            50% { opacity: 0; }
        }
    </style>
</head>
<body>
    <div id="toolbar">
        <button id="clear-btn" title="Clear chat and start a new session">New Chat</button>
    </div>
    <div id="messages"></div>
    <div id="typing-indicator">Agent is thinking...</div>
    <div id="progress-bar">
        <div class="bar" style="width: 0%"></div>
        <div id="progress-task"></div>
    </div>
    <div id="input-area">
        <input type="text" id="prompt-input" placeholder="Ask the agent..." />
        <button id="send-btn">Send</button>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const messagesEl = document.getElementById('messages');
        const typingEl = document.getElementById('typing-indicator');
        const progressBar = document.getElementById('progress-bar');
        const progressBarInner = progressBar.querySelector('.bar');
        const progressTask = document.getElementById('progress-task');
        const input = document.getElementById('prompt-input');
        const sendBtn = document.getElementById('send-btn');
        const clearBtn = document.getElementById('clear-btn');

        function escapeHtml(text) {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function renderContent(text) {
            var escaped = escapeHtml(text);
            escaped = escaped.replace(/\`\`\`[^\\n]*\\n([\\s\\S]*?)\`\`\`/g, '<pre><code>$1</code></pre>');
            escaped = escaped.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
            var parts = escaped.split(/(<pre><code>[\\s\\S]*?<\\/code><\\/pre>)/g);
            for (var i = 0; i < parts.length; i++) {
                if (parts[i].indexOf('<pre><code>') !== 0) {
                    parts[i] = parts[i].replace(/\\n/g, '<br>');
                }
            }
            return parts.join('');
        }

        function addMessageToDOM(role, content) {
            const div = document.createElement('div');
            div.className = 'message ' + role;
            div.innerHTML = renderContent(content);
            messagesEl.appendChild(div);
            div.scrollIntoView({ behavior: 'smooth' });
        }

        function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            vscode.postMessage({ type: 'sendMessage', text: text });
            input.value = '';
        }

        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
        clearBtn.addEventListener('click', function() {
            vscode.postMessage({ type: 'clearChat' });
        });

        var streamingDiv = null;
        var streamingText = '';

        window.addEventListener('message', function(event) {
            const msg = event.data;
            switch (msg.type) {
                case 'addMessage': {
                    addMessageToDOM(msg.role, msg.content);
                    break;
                }
                case 'restoreMessages': {
                    // Restore all previous messages when webview is recreated
                    messagesEl.innerHTML = '';
                    var messages = msg.messages || [];
                    for (var i = 0; i < messages.length; i++) {
                        addMessageToDOM(messages[i].role, messages[i].content);
                    }
                    break;
                }
                case 'clearMessages': {
                    messagesEl.innerHTML = '';
                    break;
                }
                case 'showPlan': {
                    const div = document.createElement('div');
                    div.className = 'message agent';
                    const tasks = msg.plan.tasks || [];
                    const lines = ['Plan:'];
                    tasks.forEach(function(t, i) {
                        lines.push((i + 1) + '. ' + t.description + ' [' + t.estimated_complexity + ']');
                    });
                    div.textContent = lines.join('\\n');
                    messagesEl.appendChild(div);
                    div.scrollIntoView({ behavior: 'smooth' });
                    break;
                }
                case 'updateProgress': {
                    progressBar.style.display = 'block';
                    progressBarInner.style.width = (msg.progress * 100) + '%';
                    progressTask.textContent = msg.currentTask || '';
                    break;
                }
                case 'setTyping': {
                    typingEl.style.display = msg.typing ? 'block' : 'none';
                    break;
                }
                case 'startStreamingMessage': {
                    streamingDiv = document.createElement('div');
                    streamingDiv.className = 'message agent streaming';
                    streamingText = '';
                    messagesEl.appendChild(streamingDiv);
                    break;
                }
                case 'streamToken': {
                    if (streamingDiv) {
                        streamingText += msg.token;
                        streamingDiv.innerHTML = renderContent(streamingText);
                        streamingDiv.scrollIntoView({ behavior: 'smooth' });
                    }
                    break;
                }
                case 'endStreamingMessage': {
                    if (streamingDiv) {
                        streamingDiv.classList.remove('streaming');
                        if (!streamingText.trim()) {
                            streamingDiv.remove();
                        }
                    }
                    streamingDiv = null;
                    streamingText = '';
                    break;
                }
            }
        });

        // Notify the extension that the webview is ready to receive restored messages
        vscode.postMessage({ type: 'webviewReady' });
    </script>
</body>
</html>`;
    }
}

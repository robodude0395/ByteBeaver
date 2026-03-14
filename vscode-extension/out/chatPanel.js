"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ChatPanel = void 0;
const vscode = __importStar(require("vscode"));
class ChatPanel {
    constructor(extensionUri, agentClient) {
        this.extensionUri = extensionUri;
        this.agentClient = agentClient;
    }
    resolveWebviewView(webviewView, _context, _token) {
        this.view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };
        webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);
        webviewView.webview.onDidReceiveMessage(async (message) => {
            if (message.type === 'sendMessage' && message.text) {
                await this.sendMessage(message.text);
            }
        });
        webviewView.onDidDispose(() => {
            this.stopStatusPolling();
        });
    }
    show() {
        if (this.view) {
            this.view.show?.(true);
        }
    }
    async sendMessage(text) {
        this.addMessage('user', text);
        this.setTyping(true);
        try {
            const workspacePath = this.getWorkspacePath();
            const response = await this.agentClient.sendPrompt(text, workspacePath, this.sessionId);
            this.sessionId = response.session_id;
            this.setTyping(false);
            if (response.plan) {
                this.displayPlan(response.plan);
            }
            this.startStatusPolling(response.session_id);
        }
        catch (error) {
            this.setTyping(false);
            const errorMessage = error instanceof Error
                ? error.message
                : 'An unknown error occurred';
            this.addMessage('system', `Error: ${errorMessage}`);
        }
    }
    addMessage(role, content) {
        this.postMessageToWebview({
            type: 'addMessage',
            role,
            content,
        });
    }
    displayPlan(plan) {
        this.postMessageToWebview({
            type: 'showPlan',
            plan,
        });
    }
    updateProgress(status) {
        const currentTask = status.current_task ?? '';
        this.postMessageToWebview({
            type: 'updateProgress',
            progress: status.progress,
            currentTask,
        });
    }
    startStatusPolling(sessionId) {
        this.stopStatusPolling();
        this.pollingInterval = setInterval(async () => {
            try {
                const status = await this.agentClient.getStatus(sessionId);
                this.updateProgress(status);
                if (status.status === 'completed' ||
                    status.status === 'error' ||
                    status.status === 'cancelled') {
                    this.stopStatusPolling();
                    if (status.status === 'completed') {
                        this.addMessage('agent', 'Task execution completed.');
                        if (status.pending_changes.length > 0) {
                            this.notifyPendingChanges(status.pending_changes);
                        }
                    }
                    else if (status.status === 'error') {
                        this.addMessage('system', 'Task execution encountered an error.');
                    }
                    else {
                        this.addMessage('system', 'Session was cancelled.');
                    }
                }
            }
            catch (_error) {
                this.stopStatusPolling();
                this.addMessage('system', 'Lost connection to agent server.');
            }
        }, 1000);
    }
    stopStatusPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = undefined;
        }
    }
    setTyping(typing) {
        this.postMessageToWebview({
            type: 'setTyping',
            typing,
        });
    }
    notifyPendingChanges(changes) {
        const fileList = changes
            .map((c) => `${c.change_type}: ${c.file_path}`)
            .join('\n');
        this.addMessage('agent', `${changes.length} file change(s) pending review:\n${fileList}`);
    }
    getWorkspacePath() {
        const folders = vscode.workspace.workspaceFolders;
        if (folders && folders.length > 0) {
            return folders[0].uri.fsPath;
        }
        return '';
    }
    postMessageToWebview(message) {
        if (this.view) {
            void this.view.webview.postMessage(message);
        }
    }
    getHtmlForWebview(_webview) {
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
    </style>
</head>
<body>
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

        function escapeHtml(text) {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function renderContent(text) {
            var escaped = escapeHtml(text);
            // Replace triple-backtick code blocks (with optional language tag)
            escaped = escaped.replace(/\`\`\`[^\\n]*\\n([\\s\\S]*?)\`\`\`/g, '<pre><code>$1</code></pre>');
            // Replace inline backtick code
            escaped = escaped.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
            // Convert newlines to <br> outside of <pre> blocks
            var parts = escaped.split(/(<pre><code>[\\s\\S]*?<\\/code><\\/pre>)/g);
            for (var i = 0; i < parts.length; i++) {
                if (parts[i].indexOf('<pre><code>') !== 0) {
                    parts[i] = parts[i].replace(/\\n/g, '<br>');
                }
            }
            return parts.join('');
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

        window.addEventListener('message', function(event) {
            const msg = event.data;
            switch (msg.type) {
                case 'addMessage': {
                    const div = document.createElement('div');
                    div.className = 'message ' + msg.role;
                    div.innerHTML = renderContent(msg.content);
                    messagesEl.appendChild(div);
                    div.scrollIntoView({ behavior: 'smooth' });
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
            }
        });
    </script>
</body>
</html>`;
    }
}
exports.ChatPanel = ChatPanel;
ChatPanel.viewType = 'agentChatPanel';
//# sourceMappingURL=chatPanel.js.map
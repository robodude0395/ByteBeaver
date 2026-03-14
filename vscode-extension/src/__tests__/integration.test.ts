/**
 * Integration tests for the VSCode extension.
 *
 * These tests verify that components work together correctly:
 * - Extension activation wires up all components
 * - Chat panel → AgentClient → DiffProvider flow
 * - Slash commands → ChatPanel → AgentClient flow
 * - DiffProvider change application workflow
 *
 * Validates: Requirements 13.1, 13.2, 13.5, 14.1-14.5
 */

import * as vscode from 'vscode';
import { activate, deactivate } from '../extension';
import { ChatPanel } from '../chatPanel';
import { DiffProvider } from '../diffProvider';
import { AgentClient, StreamEvent } from '../agentClient';
import { handleSlashCommand, SLASH_COMMANDS } from '../commands';

jest.mock('axios');

const mockVscode = vscode as any;

// ── Helpers ──────────────────────────────────────────────────────────────

function createMockExtensionContext(): vscode.ExtensionContext {
    const subscriptions: vscode.Disposable[] = [];
    return {
        subscriptions,
        extensionUri: vscode.Uri.file('/test-extension'),
        extensionPath: '/test-extension',
        globalState: { get: jest.fn(), update: jest.fn() } as any,
        workspaceState: { get: jest.fn(), update: jest.fn() } as any,
        storagePath: '/storage',
        globalStoragePath: '/global-storage',
        logPath: '/logs',
        extensionMode: 1,
        asAbsolutePath: jest.fn((p: string) => `/test-extension/${p}`),
    } as unknown as vscode.ExtensionContext;
}

function makeFakeChange(overrides: Partial<any> = {}) {
    return {
        change_id: 'c1',
        file_path: 'src/index.ts',
        change_type: 'modify',
        diff: 'const x = 1;',
        new_content: 'const x = 1;',
        ...overrides,
    };
}

/**
 * Create a mock sendPromptStreaming that fires SSE events synchronously.
 * Accepts a PromptResponse-like object and converts it to streaming events.
 */
function mockStreamingFrom(response: {
    session_id: string;
    plan?: any;
    status: string;
}): jest.Mock {
    return jest.fn(
        async (
            _prompt: string,
            _workspace: string,
            onEvent: (evt: StreamEvent) => void,
            _sessionId?: string
        ) => {
            onEvent({ event: 'session', data: { session_id: response.session_id } });
            if (response.plan) {
                onEvent({ event: 'plan', data: response.plan });
            }
            onEvent({ event: 'token', data: 'generated output' });
            onEvent({
                event: 'done',
                data: { status: response.status, session_id: response.session_id },
            });
        }
    );
}

// ── Tests ────────────────────────────────────────────────────────────────

describe('Extension Activation Integration', () => {
    let context: vscode.ExtensionContext;

    beforeEach(() => {
        jest.clearAllMocks();
        mockVscode.window.registerWebviewViewProvider = jest.fn(() => ({ dispose: jest.fn() }));
        mockVscode.workspace.getConfiguration = jest.fn(() => ({
            get: jest.fn((key: string, defaultVal: any) => {
                if (key === 'serverUrl') return 'http://localhost:8000';
                if (key === 'remoteWorkspacePath') return '';
                return defaultVal;
            }),
        }));
        context = createMockExtensionContext();
    });

    it('registers the webview view provider for the chat panel', () => {
        activate(context);

        expect(mockVscode.window.registerWebviewViewProvider).toHaveBeenCalledWith(
            'agentChatPanel',
            expect.any(ChatPanel)
        );
    });

    it('registers all expected commands', () => {
        activate(context);

        const registeredCommands = mockVscode.commands.registerCommand.mock.calls.map(
            (call: any[]) => call[0]
        );

        expect(registeredCommands).toContain('local-agent.openChat');
        expect(registeredCommands).toContain('local-agent.acceptChanges');
        expect(registeredCommands).toContain('local-agent.rejectChanges');
        expect(registeredCommands).toContain('local-agent.cancelSession');
        // Slash commands
        for (const cmd of SLASH_COMMANDS) {
            expect(registeredCommands).toContain(cmd.command);
        }
    });

    it('adds all disposables to context.subscriptions', () => {
        activate(context);

        // At minimum: webview provider + openChat + acceptChanges + rejectChanges
        // + cancelSession + 4 slash commands + statusBar + diffProvider = 12+
        expect(context.subscriptions.length).toBeGreaterThanOrEqual(8);
    });

    it('deactivate runs without error', () => {
        expect(() => deactivate()).not.toThrow();
    });
});

describe('Chat Panel ↔ Agent Client Integration', () => {
    let chatPanel: ChatPanel;
    let mockClient: jest.Mocked<AgentClient>;
    let webviewPostMessage: jest.Mock;
    let resolveView: vscode.WebviewView;

    beforeEach(() => {
        jest.clearAllMocks();
        jest.useFakeTimers();

        mockClient = {
            sendPrompt: jest.fn(),
            sendPromptStreaming: jest.fn(),
            getStatus: jest.fn(),
            applyChanges: jest.fn(),
            cancelSession: jest.fn(),
            healthCheck: jest.fn(),
            notifyChangesApplied: jest.fn(),
        } as unknown as jest.Mocked<AgentClient>;

        chatPanel = new ChatPanel(vscode.Uri.file('/ext'), mockClient);

        // Simulate resolving the webview view
        webviewPostMessage = jest.fn();
        resolveView = {
            webview: {
                options: {},
                html: '',
                postMessage: webviewPostMessage,
                onDidReceiveMessage: jest.fn(),
                cspSource: '',
                asWebviewUri: jest.fn(),
            },
            show: jest.fn(),
            onDidDispose: jest.fn(),
            visible: true,
            viewType: 'agentChatPanel',
            onDidChangeVisibility: jest.fn(),
            badge: undefined,
            title: undefined,
            description: undefined,
        } as unknown as vscode.WebviewView;

        chatPanel.resolveWebviewView(
            resolveView,
            {} as vscode.WebviewViewResolveContext,
            {} as vscode.CancellationToken
        );
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    it('sends prompt to agent and displays plan on success', async () => {
        const plan = {
            tasks: [
                { task_id: 't1', description: 'Create file', dependencies: [], estimated_complexity: 'low' },
            ],
        };
        mockClient.sendPromptStreaming = mockStreamingFrom({
            session_id: 'sess-1',
            plan,
            status: 'completed',
        });

        await chatPanel.sendMessage('build a REST API');

        // Should have sent user message, then plan
        const postCalls = webviewPostMessage.mock.calls;
        const messageTypes = postCalls.map((c: any[]) => c[0].type);

        expect(messageTypes).toContain('addMessage'); // user message
        expect(messageTypes).toContain('setTyping');   // typing indicator
        expect(messageTypes).toContain('showPlan');     // plan display

        expect(mockClient.sendPromptStreaming).toHaveBeenCalledWith(
            'build a REST API',
            expect.any(String),
            expect.any(Function),
            undefined
        );
    });

    it('displays error message when agent client fails', async () => {
        mockClient.sendPromptStreaming.mockRejectedValue(new Error('Server unreachable'));

        await chatPanel.sendMessage('do something');

        const postCalls = webviewPostMessage.mock.calls;
        const errorMessage = postCalls.find(
            (c: any[]) => c[0].type === 'addMessage' && c[0].role === 'system'
        );
        expect(errorMessage).toBeDefined();
        expect(errorMessage![0].content).toContain('Server unreachable');
    });

    it('polls status and updates progress during execution', async () => {
        mockClient.sendPromptStreaming = mockStreamingFrom({
            session_id: 'sess-1',
            plan: { tasks: [{ task_id: 't1', description: 'Task 1', dependencies: [], estimated_complexity: 'low' }] },
            status: 'completed',
        });
        mockClient.getStatus
            .mockResolvedValueOnce({
                session_id: 'sess-1',
                status: 'executing',
                current_task: 'Task 1',
                completed_tasks: [],
                pending_tasks: ['t1'],
                failed_tasks: [],
                pending_changes: [],
                progress: 0.5,
            })
            .mockResolvedValueOnce({
                session_id: 'sess-1',
                status: 'completed',
                completed_tasks: ['t1'],
                pending_tasks: [],
                failed_tasks: [],
                pending_changes: [],
                progress: 1.0,
            });

        await chatPanel.sendMessage('do work');

        // Advance timer to trigger first poll
        await jest.advanceTimersByTimeAsync(1000);
        // Advance timer to trigger second poll (completed)
        await jest.advanceTimersByTimeAsync(1000);

        const progressMessages = webviewPostMessage.mock.calls.filter(
            (c: any[]) => c[0].type === 'updateProgress'
        );
        expect(progressMessages.length).toBeGreaterThanOrEqual(1);

        // Should have a completion message
        const completionMsg = webviewPostMessage.mock.calls.find(
            (c: any[]) => c[0].type === 'addMessage' && c[0].content?.includes('completed')
        );
        expect(completionMsg).toBeDefined();
    });

    it('notifies pending changes callback when execution completes with changes', async () => {
        const pendingChangesCallback = jest.fn();
        chatPanel.onPendingChanges(pendingChangesCallback);

        const changes = [makeFakeChange()];

        mockClient.sendPromptStreaming = mockStreamingFrom({
            session_id: 'sess-1',
            plan: { tasks: [{ task_id: 't1', description: 'Task', dependencies: [], estimated_complexity: 'low' }] },
            status: 'completed',
        });
        mockClient.getStatus.mockResolvedValue({
            session_id: 'sess-1',
            status: 'completed',
            completed_tasks: ['t1'],
            pending_tasks: [],
            failed_tasks: [],
            pending_changes: changes,
            progress: 1.0,
        });

        await chatPanel.sendMessage('create a file');
        await jest.advanceTimersByTimeAsync(1000);

        expect(pendingChangesCallback).toHaveBeenCalledWith('sess-1', changes);
    });

    it('stops polling on error status', async () => {
        mockClient.sendPromptStreaming = mockStreamingFrom({
            session_id: 'sess-1',
            status: 'completed',
        });
        mockClient.getStatus.mockResolvedValue({
            session_id: 'sess-1',
            status: 'error',
            completed_tasks: [],
            pending_tasks: [],
            failed_tasks: ['t1'],
            pending_changes: [],
            progress: 0,
        });

        await chatPanel.sendMessage('fail');
        await jest.advanceTimersByTimeAsync(1000);

        // After error, polling should stop — no more getStatus calls
        const callCount = mockClient.getStatus.mock.calls.length;
        await jest.advanceTimersByTimeAsync(2000);
        expect(mockClient.getStatus.mock.calls.length).toBe(callCount);
    });
});

describe('DiffProvider Change Application Workflow', () => {
    let diffProvider: DiffProvider;
    let mockClient: jest.Mocked<AgentClient>;

    beforeEach(() => {
        jest.clearAllMocks();
        mockVscode.workspace.fs.writeFile.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.readFile.mockReset().mockResolvedValue(new Uint8Array());
        mockVscode.workspace.fs.delete.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory.mockReset().mockResolvedValue(undefined);
        mockVscode.window.showInformationMessage.mockReset().mockResolvedValue('Keep');
        mockVscode.window.showTextDocument.mockReset().mockResolvedValue(undefined);

        mockClient = {
            sendPrompt: jest.fn(),
            sendPromptStreaming: jest.fn(),
            getStatus: jest.fn(),
            applyChanges: jest.fn(),
            cancelSession: jest.fn(),
            healthCheck: jest.fn(),
            notifyChangesApplied: jest.fn(),
        } as unknown as jest.Mocked<AgentClient>;

        diffProvider = new DiffProvider(mockClient, vscode.Uri.file('/ext'));
    });

    afterEach(() => {
        diffProvider.dispose();
    });

    it('writes multiple files and notifies server on Keep', async () => {
        mockVscode.window.showInformationMessage.mockResolvedValue('Keep');

        const changes = [
            makeFakeChange({ change_id: 'c1', file_path: 'src/a.ts', new_content: 'file a' }),
            makeFakeChange({ change_id: 'c2', file_path: 'src/b.ts', new_content: 'file b' }),
            makeFakeChange({ change_id: 'c3', file_path: 'lib/c.ts', change_type: 'create', new_content: 'file c' }),
        ];

        diffProvider.setPendingChanges('sess-1', changes);
        await diffProvider.showChanges();

        // All 3 files written
        expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(3);
        // Server notified with all change IDs
        expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith(
            'sess-1',
            ['c1', 'c2', 'c3']
        );
    });

    it('reverts all files when user clicks Undo', async () => {
        const originalA = new TextEncoder().encode('original a');
        const originalB = new TextEncoder().encode('original b');
        mockVscode.workspace.fs.readFile
            .mockResolvedValueOnce(originalA)
            .mockResolvedValueOnce(originalB);
        mockVscode.window.showInformationMessage.mockResolvedValue('Undo');

        const changes = [
            makeFakeChange({ change_id: 'c1', file_path: 'src/a.ts', change_type: 'modify', new_content: 'new a' }),
            makeFakeChange({ change_id: 'c2', file_path: 'src/b.ts', change_type: 'modify', new_content: 'new b' }),
        ];

        diffProvider.setPendingChanges('sess-1', changes);
        await diffProvider.showChanges();

        // 2 writes for apply + 2 writes for restore = 4
        expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(4);
        // Server should NOT be notified on undo
        expect(mockClient.notifyChangesApplied).not.toHaveBeenCalled();
    });

    it('handles mixed create/modify/delete changes', async () => {
        const originalContent = new TextEncoder().encode('existing');
        mockVscode.workspace.fs.readFile.mockResolvedValue(originalContent);
        mockVscode.window.showInformationMessage.mockResolvedValue('Keep');

        const changes = [
            makeFakeChange({ change_id: 'c1', file_path: 'new.ts', change_type: 'create', new_content: 'new file' }),
            makeFakeChange({ change_id: 'c2', file_path: 'mod.ts', change_type: 'modify', new_content: 'modified' }),
            makeFakeChange({ change_id: 'c3', file_path: 'old.ts', change_type: 'delete' }),
        ];

        diffProvider.setPendingChanges('sess-1', changes);
        await diffProvider.showChanges();

        // create + modify = 2 writes, delete = 1 delete
        expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(2);
        expect(mockVscode.workspace.fs.delete).toHaveBeenCalledTimes(1);
    });

    it('clears state after workflow completes', async () => {
        diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
        await diffProvider.showChanges();

        expect(diffProvider.getPendingChanges()).toEqual([]);
    });
});

describe('Slash Command → Chat Panel Integration', () => {
    it('all slash commands produce expanded prompts', () => {
        for (const cmd of SLASH_COMMANDS) {
            const input = `${cmd.name} my feature`;
            const result = handleSlashCommand(input);

            expect(result.matched).toBe(true);
            expect(result.prompt).toContain('my feature');
            expect(result.prompt).not.toContain('{args}');
        }
    });

    it('unrecognized /agent command returns unmatched', () => {
        const result = handleSlashCommand('/agent unknown do stuff');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('/agent unknown do stuff');
    });

    it('non-slash input passes through unchanged', () => {
        const result = handleSlashCommand('just a normal message');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('just a normal message');
    });

    it('slash command with empty args still expands template', () => {
        const result = handleSlashCommand('/agent build');
        expect(result.matched).toBe(true);
        expect(result.prompt).toBe('Build the project: ');
    });

    it('registerCommands wires slash commands to chat panel sendMessage', async () => {
        const mockChatPanel = {
            sendMessage: jest.fn(),
        } as unknown as ChatPanel;

        // Capture the command callbacks registered
        const commandCallbacks: Record<string, Function> = {};
        mockVscode.commands.registerCommand.mockImplementation(
            (cmd: string, cb: Function) => {
                commandCallbacks[cmd] = cb;
                return { dispose: jest.fn() };
            }
        );

        // Simulate user providing input
        mockVscode.window.showInputBox.mockResolvedValue('a REST API');

        const { registerCommands } = require('../commands');
        registerCommands(mockChatPanel);

        // Execute the build command
        await commandCallbacks['local-agent.build']();

        expect(mockChatPanel.sendMessage).toHaveBeenCalledWith(
            'Build the project: a REST API'
        );
    });

    it('slash command does nothing when user cancels input box', async () => {
        const mockChatPanel = {
            sendMessage: jest.fn(),
        } as unknown as ChatPanel;

        const commandCallbacks: Record<string, Function> = {};
        mockVscode.commands.registerCommand.mockImplementation(
            (cmd: string, cb: Function) => {
                commandCallbacks[cmd] = cb;
                return { dispose: jest.fn() };
            }
        );

        // User cancels the input box
        mockVscode.window.showInputBox.mockResolvedValue(undefined);

        const { registerCommands } = require('../commands');
        registerCommands(mockChatPanel);

        await commandCallbacks['local-agent.implement']();

        expect(mockChatPanel.sendMessage).not.toHaveBeenCalled();
    });
});

describe('Chat Panel → DiffProvider End-to-End Flow', () => {
    let chatPanel: ChatPanel;
    let diffProvider: DiffProvider;
    let mockClient: jest.Mocked<AgentClient>;

    beforeEach(() => {
        jest.clearAllMocks();
        jest.useFakeTimers();

        mockVscode.workspace.fs.writeFile.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.readFile.mockReset().mockResolvedValue(new Uint8Array());
        mockVscode.workspace.fs.createDirectory.mockReset().mockResolvedValue(undefined);
        mockVscode.window.showInformationMessage.mockReset().mockResolvedValue('Keep');
        mockVscode.window.showTextDocument.mockReset().mockResolvedValue(undefined);

        mockClient = {
            sendPrompt: jest.fn(),
            sendPromptStreaming: jest.fn(),
            getStatus: jest.fn(),
            applyChanges: jest.fn(),
            cancelSession: jest.fn(),
            healthCheck: jest.fn(),
            notifyChangesApplied: jest.fn(),
        } as unknown as jest.Mocked<AgentClient>;

        chatPanel = new ChatPanel(vscode.Uri.file('/ext'), mockClient);
        diffProvider = new DiffProvider(mockClient, vscode.Uri.file('/ext'));

        // Wire them together like extension.ts does
        chatPanel.onPendingChanges((sessionId, changes) => {
            diffProvider.setPendingChanges(sessionId, changes);
            void diffProvider.showChanges();
        });

        // Resolve the webview
        const resolveView = {
            webview: {
                options: {},
                html: '',
                postMessage: jest.fn(),
                onDidReceiveMessage: jest.fn(),
            },
            show: jest.fn(),
            onDidDispose: jest.fn(),
        } as unknown as vscode.WebviewView;

        chatPanel.resolveWebviewView(
            resolveView,
            {} as vscode.WebviewViewResolveContext,
            {} as vscode.CancellationToken
        );
    });

    afterEach(() => {
        jest.useRealTimers();
        diffProvider.dispose();
    });

    it('prompt → execution → changes written to disk → server notified', async () => {
        const fileChanges = [
            makeFakeChange({ change_id: 'c1', file_path: 'src/app.ts', new_content: 'const app = express();' }),
        ];

        mockClient.sendPromptStreaming = mockStreamingFrom({
            session_id: 'sess-1',
            plan: { tasks: [{ task_id: 't1', description: 'Create app', dependencies: [], estimated_complexity: 'low' }] },
            status: 'completed',
        });
        mockClient.getStatus.mockResolvedValue({
            session_id: 'sess-1',
            status: 'completed',
            completed_tasks: ['t1'],
            pending_tasks: [],
            failed_tasks: [],
            pending_changes: fileChanges,
            progress: 1.0,
        });

        await chatPanel.sendMessage('create an express app');
        await jest.advanceTimersByTimeAsync(1000);

        // Allow microtasks (showChanges is async)
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();

        // File should have been written
        expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalled();
        // Server should have been notified
        expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith('sess-1', ['c1']);
    });
});

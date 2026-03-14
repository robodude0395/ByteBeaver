import * as vscode from 'vscode';
import { AgentClient } from './agentClient';
import { ChatPanel } from './chatPanel';
import { DiffProvider } from './diffProvider';
import { AgentStatusBar } from './statusBar';
import { registerCommands } from './commands';

export function activate(context: vscode.ExtensionContext): void {
    // Read configuration
    const config = vscode.workspace.getConfiguration('agent');
    const serverUrl = config.get<string>('serverUrl', 'http://localhost:8000');

    // Initialize agent client
    const agentClient = new AgentClient(serverUrl);

    // Create and register chat panel
    const chatPanel = new ChatPanel(context.extensionUri, agentClient);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            ChatPanel.viewType,
            chatPanel
        )
    );

    // Create diff provider
    const diffProvider = new DiffProvider(agentClient, context.extensionUri);
    context.subscriptions.push(diffProvider);

    // Wire up pending changes from chat to diff provider
    chatPanel.onPendingChanges((sessionId, changes) => {
        diffProvider.setPendingChanges(sessionId, changes);
        void diffProvider.showChanges();
    });

    // Create status bar
    const statusBar = new AgentStatusBar();
    context.subscriptions.push(statusBar);

    // Register openChat command
    context.subscriptions.push(
        vscode.commands.registerCommand('local-agent.openChat', () => {
            chatPanel.show();
        })
    );

    // Register undo changes command (for programmatic use)
    context.subscriptions.push(
        vscode.commands.registerCommand('local-agent.acceptChanges', () => {
            void diffProvider.acceptChanges();
        }),
        vscode.commands.registerCommand('local-agent.rejectChanges', () => {
            void diffProvider.rejectChanges();
        })
    );

    // Register slash commands (build, implement, refactor, explain)
    const commandDisposables = registerCommands(chatPanel);
    context.subscriptions.push(...commandDisposables);

    // Register cancelSession command
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'local-agent.cancelSession',
            async () => {
                const sessionId = await vscode.window.showInputBox({
                    prompt: 'Enter session ID to cancel',
                    placeHolder: 'session-id',
                });
                if (sessionId) {
                    try {
                        await agentClient.cancelSession(sessionId);
                        void vscode.window.showInformationMessage(
                            'Session cancelled successfully.'
                        );
                    } catch (error) {
                        const message =
                            error instanceof Error
                                ? error.message
                                : 'Unknown error';
                        void vscode.window.showErrorMessage(
                            `Failed to cancel session: ${message}`
                        );
                    }
                }
            }
        )
    );
}

export function deactivate(): void {
    // Cleanup handled by disposables in context.subscriptions
}

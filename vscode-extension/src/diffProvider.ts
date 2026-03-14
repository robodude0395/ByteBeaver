import * as vscode from 'vscode';
import { AgentClient, FileChangeInfo } from './agentClient';

/**
 * Content provider for showing proposed file content in diff views.
 * Stores content keyed by URI and serves it to the diff editor.
 */
export class ProposedContentProvider
    implements vscode.TextDocumentContentProvider
{
    private contentMap = new Map<string, string>();
    private _onDidChange = new vscode.EventEmitter<vscode.Uri>();

    public readonly onDidChangeEmitter = this._onDidChange;
    public readonly onDidChange = this._onDidChange.event;

    public setContent(uri: vscode.Uri, content: string): void {
        this.contentMap.set(uri.toString(), content);
        this._onDidChange.fire(uri);
    }

    public provideTextDocumentContent(uri: vscode.Uri): string {
        return this.contentMap.get(uri.toString()) ?? '';
    }

    public clear(): void {
        this.contentMap.clear();
    }

    public dispose(): void {
        this._onDidChange.dispose();
        this.contentMap.clear();
    }
}

/**
 * Manages diff previews and accept/reject workflow for proposed code changes.
 */
export class DiffProvider {
    private pendingChanges: FileChangeInfo[] = [];
    private sessionId: string | undefined;
    private acceptButton: vscode.StatusBarItem | undefined;
    private rejectButton: vscode.StatusBarItem | undefined;
    private readonly agentClient: AgentClient;
    private readonly contentProvider: ProposedContentProvider;
    private contentProviderRegistration: vscode.Disposable | undefined;

    public static readonly scheme = 'agent-proposed';

    constructor(agentClient: AgentClient, _extensionUri: vscode.Uri) {
        this.agentClient = agentClient;
        this.contentProvider = new ProposedContentProvider();
        this.contentProviderRegistration =
            vscode.workspace.registerTextDocumentContentProvider(
                DiffProvider.scheme,
                this.contentProvider
            );
    }

    /**
     * Store pending changes and show status bar actions.
     */
    public setPendingChanges(
        sessionId: string,
        changes: FileChangeInfo[]
    ): void {
        this.sessionId = sessionId;
        this.pendingChanges = [...changes];
        this.showChangeActions();
    }

    /**
     * Display diffs for all pending changes. Opens the first change immediately.
     */
    public async showChanges(): Promise<void> {
        if (this.pendingChanges.length === 0) {
            return;
        }

        await this.showDiff(this.pendingChanges[0]);
    }

    /**
     * Show diff for a single file change.
     */
    public async showDiff(change: FileChangeInfo): Promise<void> {
        const proposedUri = vscode.Uri.parse(
            `${DiffProvider.scheme}:${change.file_path}?change=${change.change_id}`
        );

        // Set the proposed content from the diff field
        this.contentProvider.setContent(proposedUri, change.diff);

        const workspaceFolders = vscode.workspace.workspaceFolders;
        const workspaceRoot = workspaceFolders?.[0]?.uri;

        let originalUri: vscode.Uri;
        if (workspaceRoot) {
            originalUri = vscode.Uri.joinPath(workspaceRoot, change.file_path);
        } else {
            originalUri = vscode.Uri.file(change.file_path);
        }

        const title = `${change.file_path} (Proposed Changes)`;

        await vscode.commands.executeCommand(
            'vscode.diff',
            originalUri,
            proposedUri,
            title
        );
    }

    /**
     * Show accept/reject buttons in the status bar.
     */
    public showChangeActions(): void {
        if (!this.acceptButton) {
            this.acceptButton = vscode.window.createStatusBarItem(
                vscode.StatusBarAlignment.Right,
                101
            );
        }
        this.acceptButton.text = '$(check) Accept Changes';
        this.acceptButton.command = 'local-agent.acceptChanges';
        this.acceptButton.tooltip = 'Accept all proposed changes';
        this.acceptButton.show();

        if (!this.rejectButton) {
            this.rejectButton = vscode.window.createStatusBarItem(
                vscode.StatusBarAlignment.Right,
                100
            );
        }
        this.rejectButton.text = '$(x) Reject Changes';
        this.rejectButton.command = 'local-agent.rejectChanges';
        this.rejectButton.tooltip = 'Reject all proposed changes';
        this.rejectButton.show();
    }

    /**
     * Accept all pending changes by calling the agent server.
     */
    public async acceptChanges(): Promise<void> {
        if (!this.sessionId || this.pendingChanges.length === 0) {
            return;
        }

        const changeIds = this.pendingChanges.map((c) => c.change_id);

        try {
            const result = await this.agentClient.applyChanges(
                this.sessionId,
                changeIds
            );

            if (result.applied.length > 0) {
                void vscode.window.showInformationMessage(
                    `Applied ${result.applied.length} change(s) successfully.`
                );
            }

            if (result.failed.length > 0) {
                const failedFiles = result.failed.join(', ');
                void vscode.window.showWarningMessage(
                    `Failed to apply changes: ${failedFiles}`
                );
            }
        } catch (error) {
            const message =
                error instanceof Error
                    ? error.message
                    : 'Unknown error';
            void vscode.window.showErrorMessage(
                `Failed to apply changes: ${message}`
            );
        } finally {
            this.pendingChanges = [];
            this.sessionId = undefined;
            this.contentProvider.clear();
            this.hideChangeActions();
        }
    }

    /**
     * Reject all pending changes and clear state.
     */
    public async rejectChanges(): Promise<void> {
        this.pendingChanges = [];
        this.sessionId = undefined;
        this.contentProvider.clear();
        this.hideChangeActions();

        void vscode.window.showInformationMessage(
            'All proposed changes have been rejected.'
        );
    }

    /**
     * Hide the accept/reject status bar buttons.
     */
    public hideChangeActions(): void {
        if (this.acceptButton) {
            this.acceptButton.hide();
        }
        if (this.rejectButton) {
            this.rejectButton.hide();
        }
    }

    /**
     * Get the current list of pending changes.
     */
    public getPendingChanges(): FileChangeInfo[] {
        return [...this.pendingChanges];
    }

    /**
     * Clean up all resources.
     */
    public dispose(): void {
        this.hideChangeActions();
        this.acceptButton?.dispose();
        this.rejectButton?.dispose();
        this.contentProvider.dispose();
        this.contentProviderRegistration?.dispose();
        this.pendingChanges = [];
        this.sessionId = undefined;
    }
}

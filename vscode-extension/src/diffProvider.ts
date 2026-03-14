import * as vscode from 'vscode';
import { AgentClient, FileChangeInfo } from './agentClient';

interface WriteResult {
    changeId: string;
    filePath: string;
    success: boolean;
    error?: string;
}

interface AppliedChange {
    change: FileChangeInfo;
    originalContent: Uint8Array | null; // null means file didn't exist before
    fileUri: vscode.Uri;
}

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
 * Manages the write-first workflow for proposed code changes.
 *
 * Flow (Copilot-style):
 * 1. Changes arrive from the agent server
 * 2. Files are written to disk immediately
 * 3. User sees a notification with Keep / Undo
 * 4. Keep: notify server, done
 * 5. Undo: revert all files to their original state
 */
export class DiffProvider {
    private pendingChanges: FileChangeInfo[] = [];
    private appliedChanges: AppliedChange[] = [];
    private sessionId: string | undefined;
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
     * Store pending changes, write them to disk immediately,
     * then prompt the user to keep or undo.
     */
    public setPendingChanges(
        sessionId: string,
        changes: FileChangeInfo[]
    ): void {
        this.sessionId = sessionId;
        this.pendingChanges = [...changes];
    }

    /**
     * Write all pending changes to disk immediately, then show keep/undo prompt.
     */
    public async showChanges(): Promise<void> {
        if (this.pendingChanges.length === 0) {
            return;
        }

        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
        if (!workspaceRoot) {
            vscode.window.showErrorMessage('No workspace folder open. Cannot write files.');
            return;
        }

        // Write all changes to disk, saving originals for undo
        const results: WriteResult[] = [];
        this.appliedChanges = [];

        for (const change of this.pendingChanges) {
            const fileUri = vscode.Uri.joinPath(workspaceRoot, change.file_path);

            // Save original content for undo
            let originalContent: Uint8Array | null = null;
            if (change.change_type !== 'create') {
                try {
                    originalContent = await vscode.workspace.fs.readFile(fileUri);
                } catch {
                    // File doesn't exist — that's fine for create
                    originalContent = null;
                }
            }

            const result = await this.applyChangeLocally(workspaceRoot, change);
            results.push(result);

            if (result.success) {
                this.appliedChanges.push({ change, originalContent, fileUri });
            }
        }

        const successes = results.filter((r) => r.success);
        const failures = results.filter((r) => !r.success);

        if (successes.length === 0) {
            vscode.window.showErrorMessage(
                `All ${failures.length} change(s) failed to apply.`
            );
            this.clearState();
            return;
        }

        // Open the first changed file so the user can see what happened
        if (this.appliedChanges.length > 0) {
            const firstUri = this.appliedChanges[0].fileUri;
            try {
                await vscode.window.showTextDocument(firstUri, { preview: true });
            } catch {
                // Non-critical — file might not be openable
            }
        }

        // Build the prompt message
        let message: string;
        if (failures.length === 0) {
            message = `Agent applied ${successes.length} file change(s).`;
        } else {
            const failedPaths = failures.map((f) => f.filePath).join(', ');
            message = `Agent applied ${successes.length} change(s), ${failures.length} failed: ${failedPaths}`;
        }

        // Show keep/undo notification
        const choice = await vscode.window.showInformationMessage(
            message,
            'Keep',
            'Undo'
        );

        if (choice === 'Undo') {
            await this.undoChanges();
        } else {
            // Keep (or dismissed) — notify server
            await this.acceptChanges();
        }
    }

    /**
     * Extract the writable content from a FileChangeInfo.
     * Uses new_content (actual file content) when available.
     * Falls back to diff with unified diff markers stripped.
     */
    private extractContent(change: FileChangeInfo): Uint8Array {
        let content = change.new_content ?? change.diff;
        // Safety net: if content looks like a unified diff, strip the markers
        if (content.startsWith('---') || content.startsWith('+++') || content.startsWith('@@')) {
            content = content
                .split('\n')
                .filter(line => !line.startsWith('---') && !line.startsWith('+++') && !line.startsWith('@@'))
                .map(line => {
                    if (line.startsWith('+')) { return line.substring(1); }
                    if (line.startsWith('-')) { return null; }
                    if (line.startsWith(' ')) { return line.substring(1); }
                    return line;
                })
                .filter((line): line is string => line !== null)
                .join('\n');
        }
        return new TextEncoder().encode(content);
    }

    /**
     * Ensure all parent directories exist for a given file URI.
     */
    private async ensureParentDirectories(fileUri: vscode.Uri): Promise<void> {
        const filePath = fileUri.path;
        const lastSlash = filePath.lastIndexOf('/');
        if (lastSlash <= 0) {
            return;
        }
        const parentPath = filePath.substring(0, lastSlash);
        const parentUri = vscode.Uri.parse(`${fileUri.scheme}://${parentPath}`);
        await vscode.workspace.fs.createDirectory(parentUri);
    }

    /**
     * Write a single file change to the local workspace filesystem.
     */
    private async applyChangeLocally(
        workspaceRoot: vscode.Uri,
        change: FileChangeInfo
    ): Promise<WriteResult> {
        const fileUri = vscode.Uri.joinPath(workspaceRoot, change.file_path);
        try {
            if (change.change_type === 'delete') {
                await vscode.workspace.fs.delete(fileUri);
            } else {
                await this.ensureParentDirectories(fileUri);
                await vscode.workspace.fs.writeFile(
                    fileUri,
                    this.extractContent(change)
                );
            }
            return {
                changeId: change.change_id,
                filePath: change.file_path,
                success: true,
            };
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            return {
                changeId: change.change_id,
                filePath: change.file_path,
                success: false,
                error: message,
            };
        }
    }

    /**
     * Notify server that changes were kept. Called when user clicks Keep or dismisses.
     */
    public async acceptChanges(): Promise<void> {
        if (this.appliedChanges.length > 0 && this.sessionId) {
            const changeIds = this.appliedChanges.map((a) => a.change.change_id);
            this.agentClient.notifyChangesApplied(this.sessionId, changeIds);
        }
        this.clearState();
    }

    /**
     * Revert all applied changes to their original state.
     */
    public async undoChanges(): Promise<void> {
        for (const applied of this.appliedChanges) {
            try {
                if (applied.change.change_type === 'create') {
                    // File was created — delete it
                    await vscode.workspace.fs.delete(applied.fileUri);
                } else if (applied.change.change_type === 'delete') {
                    // File was deleted — restore original content
                    if (applied.originalContent) {
                        await this.ensureParentDirectories(applied.fileUri);
                        await vscode.workspace.fs.writeFile(
                            applied.fileUri,
                            applied.originalContent
                        );
                    }
                } else {
                    // File was modified — restore original content
                    if (applied.originalContent) {
                        await vscode.workspace.fs.writeFile(
                            applied.fileUri,
                            applied.originalContent
                        );
                    }
                }
            } catch (error) {
                const msg = error instanceof Error ? error.message : String(error);
                console.error(`Failed to undo ${applied.change.file_path}: ${msg}`);
            }
        }

        vscode.window.showInformationMessage('Changes undone.');
        this.clearState();
    }

    /**
     * Reject all pending changes (alias for undo for backward compat).
     */
    public async rejectChanges(): Promise<void> {
        await this.undoChanges();
    }

    private clearState(): void {
        this.pendingChanges = [];
        this.appliedChanges = [];
        this.sessionId = undefined;
        this.contentProvider.clear();
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
        this.contentProvider.dispose();
        this.contentProviderRegistration?.dispose();
        this.pendingChanges = [];
        this.appliedChanges = [];
        this.sessionId = undefined;
    }
}

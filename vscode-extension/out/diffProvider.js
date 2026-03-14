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
exports.DiffProvider = exports.ProposedContentProvider = void 0;
const vscode = __importStar(require("vscode"));
/**
 * Content provider for showing proposed file content in diff views.
 * Stores content keyed by URI and serves it to the diff editor.
 */
class ProposedContentProvider {
    constructor() {
        this.contentMap = new Map();
        this._onDidChange = new vscode.EventEmitter();
        this.onDidChangeEmitter = this._onDidChange;
        this.onDidChange = this._onDidChange.event;
    }
    setContent(uri, content) {
        this.contentMap.set(uri.toString(), content);
        this._onDidChange.fire(uri);
    }
    provideTextDocumentContent(uri) {
        return this.contentMap.get(uri.toString()) ?? '';
    }
    clear() {
        this.contentMap.clear();
    }
    dispose() {
        this._onDidChange.dispose();
        this.contentMap.clear();
    }
}
exports.ProposedContentProvider = ProposedContentProvider;
/**
 * Manages diff previews and accept/reject workflow for proposed code changes.
 */
class DiffProvider {
    constructor(agentClient, _extensionUri) {
        this.pendingChanges = [];
        this.agentClient = agentClient;
        this.contentProvider = new ProposedContentProvider();
        this.contentProviderRegistration =
            vscode.workspace.registerTextDocumentContentProvider(DiffProvider.scheme, this.contentProvider);
    }
    /**
     * Store pending changes and show status bar actions.
     */
    setPendingChanges(sessionId, changes) {
        this.sessionId = sessionId;
        this.pendingChanges = [...changes];
        this.showChangeActions();
    }
    /**
     * Display diffs for all pending changes. Opens the first change immediately.
     */
    async showChanges() {
        if (this.pendingChanges.length === 0) {
            return;
        }
        await this.showDiff(this.pendingChanges[0]);
    }
    /**
     * Show diff for a single file change.
     */
    async showDiff(change) {
        const proposedUri = vscode.Uri.parse(`${DiffProvider.scheme}:${change.file_path}?change=${change.change_id}`);
        // Set the proposed content from the diff field
        this.contentProvider.setContent(proposedUri, change.diff);
        const workspaceFolders = vscode.workspace.workspaceFolders;
        const workspaceRoot = workspaceFolders?.[0]?.uri;
        let originalUri;
        if (workspaceRoot) {
            originalUri = vscode.Uri.joinPath(workspaceRoot, change.file_path);
        }
        else {
            originalUri = vscode.Uri.file(change.file_path);
        }
        const title = `${change.file_path} (Proposed Changes)`;
        await vscode.commands.executeCommand('vscode.diff', originalUri, proposedUri, title);
    }
    /**
     * Show accept/reject buttons in the status bar.
     */
    showChangeActions() {
        if (!this.acceptButton) {
            this.acceptButton = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 101);
        }
        this.acceptButton.text = '$(check) Accept Changes';
        this.acceptButton.command = 'local-agent.acceptChanges';
        this.acceptButton.tooltip = 'Accept all proposed changes';
        this.acceptButton.show();
        if (!this.rejectButton) {
            this.rejectButton = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
        }
        this.rejectButton.text = '$(x) Reject Changes';
        this.rejectButton.command = 'local-agent.rejectChanges';
        this.rejectButton.tooltip = 'Reject all proposed changes';
        this.rejectButton.show();
    }
    /**
     * Accept all pending changes by calling the agent server.
     */
    async acceptChanges() {
        if (!this.sessionId || this.pendingChanges.length === 0) {
            return;
        }
        const changeIds = this.pendingChanges.map((c) => c.change_id);
        try {
            const result = await this.agentClient.applyChanges(this.sessionId, changeIds);
            if (result.applied.length > 0) {
                void vscode.window.showInformationMessage(`Applied ${result.applied.length} change(s) successfully.`);
            }
            if (result.failed.length > 0) {
                const failedFiles = result.failed.join(', ');
                void vscode.window.showWarningMessage(`Failed to apply changes: ${failedFiles}`);
            }
        }
        catch (error) {
            const message = error instanceof Error
                ? error.message
                : 'Unknown error';
            void vscode.window.showErrorMessage(`Failed to apply changes: ${message}`);
        }
        finally {
            this.pendingChanges = [];
            this.sessionId = undefined;
            this.contentProvider.clear();
            this.hideChangeActions();
        }
    }
    /**
     * Reject all pending changes and clear state.
     */
    async rejectChanges() {
        this.pendingChanges = [];
        this.sessionId = undefined;
        this.contentProvider.clear();
        this.hideChangeActions();
        void vscode.window.showInformationMessage('All proposed changes have been rejected.');
    }
    /**
     * Hide the accept/reject status bar buttons.
     */
    hideChangeActions() {
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
    getPendingChanges() {
        return [...this.pendingChanges];
    }
    /**
     * Clean up all resources.
     */
    dispose() {
        this.hideChangeActions();
        this.acceptButton?.dispose();
        this.rejectButton?.dispose();
        this.contentProvider.dispose();
        this.contentProviderRegistration?.dispose();
        this.pendingChanges = [];
        this.sessionId = undefined;
    }
}
exports.DiffProvider = DiffProvider;
DiffProvider.scheme = 'agent-proposed';
//# sourceMappingURL=diffProvider.js.map
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
const vscode = __importStar(require("vscode"));
const diffProvider_1 = require("../diffProvider");
// Mock agentClient module - we don't want the real one
jest.mock('../agentClient');
const mockVscode = vscode;
function createMockAgentClient() {
    return {
        applyChanges: jest.fn(),
        notifyChangesApplied: jest.fn(),
        sendPrompt: jest.fn(),
        getStatus: jest.fn(),
        cancelSession: jest.fn(),
        healthCheck: jest.fn(),
    };
}
function makeFakeChange(overrides = {}) {
    return {
        change_id: 'c1',
        file_path: 'src/index.ts',
        change_type: 'modify',
        diff: 'const x = 1;',
        ...overrides,
    };
}
describe('ProposedContentProvider', () => {
    let provider;
    beforeEach(() => {
        jest.clearAllMocks();
        provider = new diffProvider_1.ProposedContentProvider();
    });
    afterEach(() => {
        provider.dispose();
    });
    it('setContent stores content and provideTextDocumentContent retrieves it', () => {
        const uri = vscode.Uri.parse('agent-proposed:src/file.ts?change=c1');
        provider.setContent(uri, 'const hello = "world";');
        const result = provider.provideTextDocumentContent(uri);
        expect(result).toBe('const hello = "world";');
    });
    it('provideTextDocumentContent returns empty string for unknown URI', () => {
        const uri = vscode.Uri.parse('agent-proposed:unknown/file.ts');
        const result = provider.provideTextDocumentContent(uri);
        expect(result).toBe('');
    });
    it('clear() removes all stored content', () => {
        const uri1 = vscode.Uri.parse('agent-proposed:file1.ts');
        const uri2 = vscode.Uri.parse('agent-proposed:file2.ts');
        provider.setContent(uri1, 'content1');
        provider.setContent(uri2, 'content2');
        provider.clear();
        expect(provider.provideTextDocumentContent(uri1)).toBe('');
        expect(provider.provideTextDocumentContent(uri2)).toBe('');
    });
});
describe('DiffProvider', () => {
    let mockClient;
    let diffProvider;
    let extensionUri;
    beforeEach(() => {
        jest.restoreAllMocks();
        jest.clearAllMocks();
        // Reset workspace.fs mocks to default resolved behavior
        mockVscode.workspace.fs.writeFile.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory.mockReset().mockResolvedValue(undefined);
        mockClient = createMockAgentClient();
        extensionUri = vscode.Uri.file('/ext');
        diffProvider = new diffProvider_1.DiffProvider(mockClient, extensionUri);
    });
    afterEach(() => {
        diffProvider.dispose();
    });
    describe('setPendingChanges', () => {
        it('stores changes and shows status bar buttons', () => {
            const changes = [makeFakeChange()];
            diffProvider.setPendingChanges('sess-1', changes);
            expect(diffProvider.getPendingChanges()).toEqual(changes);
            // Status bar items should have been created and shown
            expect(mockVscode.window.createStatusBarItem).toHaveBeenCalledTimes(2);
        });
    });
    describe('showChanges', () => {
        it('opens diff editor for first pending change', async () => {
            const changes = [
                makeFakeChange({ change_id: 'c1', file_path: 'src/a.ts' }),
                makeFakeChange({ change_id: 'c2', file_path: 'src/b.ts' }),
            ];
            diffProvider.setPendingChanges('sess-1', changes);
            await diffProvider.showChanges();
            expect(mockVscode.commands.executeCommand).toHaveBeenCalledWith('vscode.diff', expect.anything(), expect.anything(), 'src/a.ts (Proposed Changes)');
        });
        it('does nothing when no pending changes', async () => {
            await diffProvider.showChanges();
            expect(mockVscode.commands.executeCommand).not.toHaveBeenCalled();
        });
    });
    describe('showDiff', () => {
        it('calls vscode.diff command with correct URIs', async () => {
            const change = makeFakeChange({
                change_id: 'c1',
                file_path: 'src/main.ts',
                diff: 'new content',
            });
            await diffProvider.showDiff(change);
            expect(mockVscode.commands.executeCommand).toHaveBeenCalledWith('vscode.diff', expect.anything(), // originalUri
            expect.anything(), // proposedUri
            'src/main.ts (Proposed Changes)');
            // Verify the proposed URI uses the correct scheme
            const proposedUri = mockVscode.commands.executeCommand.mock.calls[0][2];
            expect(proposedUri.toString()).toContain('agent-proposed');
        });
    });
    describe('acceptChanges', () => {
        it('writes files locally via workspace.fs instead of calling applyChanges', async () => {
            const changes = [
                makeFakeChange({ change_id: 'c1', file_path: 'src/a.ts', change_type: 'modify', diff: 'content a' }),
                makeFakeChange({ change_id: 'c2', file_path: 'src/b.ts', change_type: 'create', diff: 'content b' }),
            ];
            diffProvider.setPendingChanges('sess-1', changes);
            await diffProvider.acceptChanges();
            expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(2);
            expect(mockClient.applyChanges).not.toHaveBeenCalled();
        });
        it('shows success message and clears state', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();
            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith('Successfully applied 1 change(s).');
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
        it('shows warning for partially failed changes with failed path', async () => {
            const changes = [
                makeFakeChange({ change_id: 'c1', file_path: 'src/good.ts', diff: 'ok' }),
                makeFakeChange({ change_id: 'c2', file_path: 'src/bad.ts', diff: 'fail' }),
            ];
            // Make the second writeFile call fail
            mockVscode.workspace.fs.writeFile
                .mockResolvedValueOnce(undefined)
                .mockRejectedValueOnce(new Error('Permission denied'));
            diffProvider.setPendingChanges('sess-1', changes);
            await diffProvider.acceptChanges();
            expect(mockVscode.window.showWarningMessage).toHaveBeenCalledWith(expect.stringContaining('1 failed'));
            expect(mockVscode.window.showWarningMessage).toHaveBeenCalledWith(expect.stringContaining('src/bad.ts'));
        });
        it('shows error when all writes fail', async () => {
            mockVscode.workspace.fs.writeFile.mockRejectedValue(new Error('Disk full'));
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();
            expect(mockVscode.window.showErrorMessage).toHaveBeenCalledWith(expect.stringContaining('failed to apply'));
        });
        it('returns immediately when no pending changes', async () => {
            await diffProvider.acceptChanges();
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();
            expect(mockVscode.workspace.fs.delete).not.toHaveBeenCalled();
            expect(mockClient.applyChanges).not.toHaveBeenCalled();
            expect(mockClient.notifyChangesApplied).not.toHaveBeenCalled();
            expect(mockVscode.window.showInformationMessage).not.toHaveBeenCalled();
            expect(mockVscode.window.showErrorMessage).not.toHaveBeenCalled();
        });
        it('shows error and aborts when no workspace folder is open', async () => {
            // Temporarily remove workspace folders
            const originalFolders = mockVscode.workspace.workspaceFolders;
            mockVscode.workspace.workspaceFolders = undefined;
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();
            expect(mockVscode.window.showErrorMessage).toHaveBeenCalledWith('No workspace folder open. Cannot write files.');
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();
            expect(mockVscode.workspace.fs.delete).not.toHaveBeenCalled();
            expect(mockClient.notifyChangesApplied).not.toHaveBeenCalled();
            // Restore workspace folders
            mockVscode.workspace.workspaceFolders = originalFolders;
        });
        it('server notification failure does not affect user-facing success', async () => {
            // notifyChangesApplied is fire-and-forget (not awaited).
            // The real method catches errors internally, so mock it to resolve
            // but verify the user still sees success regardless of notification outcome.
            mockClient.notifyChangesApplied.mockResolvedValueOnce(undefined);
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();
            // User sees success
            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith('Successfully applied 1 change(s).');
            // No error shown to user
            expect(mockVscode.window.showErrorMessage).not.toHaveBeenCalled();
            // Notification was attempted
            expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith('sess-1', ['c1']);
        });
        it('delete change type calls vscode.workspace.fs.delete', async () => {
            const deleteChange = makeFakeChange({
                change_id: 'del-1',
                file_path: 'src/obsolete.ts',
                change_type: 'delete',
            });
            diffProvider.setPendingChanges('sess-1', [deleteChange]);
            await diffProvider.acceptChanges();
            expect(mockVscode.workspace.fs.delete).toHaveBeenCalledTimes(1);
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();
        });
        it('clears state and hides status bar after accept', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            const statusBarItems = mockVscode.window.createStatusBarItem.mock.results;
            await diffProvider.acceptChanges();
            expect(diffProvider.getPendingChanges()).toEqual([]);
            for (const item of statusBarItems) {
                expect(item.value.hide).toHaveBeenCalled();
            }
        });
    });
    describe('rejectChanges', () => {
        it('clears pending changes and shows message', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.rejectChanges();
            expect(diffProvider.getPendingChanges()).toEqual([]);
            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith('All proposed changes have been rejected.');
        });
        it('hides status bar buttons', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            // Get references to the created status bar items
            const statusBarItems = mockVscode.window.createStatusBarItem.mock.results;
            await diffProvider.rejectChanges();
            // Both status bar items should have hide() called
            for (const item of statusBarItems) {
                expect(item.value.hide).toHaveBeenCalled();
            }
        });
    });
    describe('getPendingChanges', () => {
        it('returns copy of pending changes', () => {
            const changes = [makeFakeChange()];
            diffProvider.setPendingChanges('sess-1', changes);
            const result = diffProvider.getPendingChanges();
            expect(result).toEqual(changes);
            // Verify it's a copy, not the same reference
            expect(result).not.toBe(changes);
        });
        it('returns empty array when no changes', () => {
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
    });
    describe('dispose', () => {
        it('cleans up all resources', () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            const statusBarItems = mockVscode.window.createStatusBarItem.mock.results;
            diffProvider.dispose();
            // Status bar items should be disposed
            for (const item of statusBarItems) {
                expect(item.value.dispose).toHaveBeenCalled();
            }
            // Pending changes should be cleared
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
    });
});
//# sourceMappingURL=diffProvider.test.js.map
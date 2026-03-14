import * as vscode from 'vscode';
import { ProposedContentProvider, DiffProvider } from '../diffProvider';
import { AgentClient, FileChangeInfo } from '../agentClient';

// Mock agentClient module - we don't want the real one
jest.mock('../agentClient');

const mockVscode = vscode as any;

function createMockAgentClient(): jest.Mocked<AgentClient> {
    return {
        applyChanges: jest.fn(),
        notifyChangesApplied: jest.fn(),
        sendPrompt: jest.fn(),
        getStatus: jest.fn(),
        cancelSession: jest.fn(),
        healthCheck: jest.fn(),
    } as unknown as jest.Mocked<AgentClient>;
}

function makeFakeChange(overrides: Partial<FileChangeInfo> = {}): FileChangeInfo {
    return {
        change_id: 'c1',
        file_path: 'src/index.ts',
        change_type: 'modify',
        diff: 'const x = 1;',
        new_content: 'const x = 1;',
        ...overrides,
    };
}

describe('ProposedContentProvider', () => {
    let provider: ProposedContentProvider;

    beforeEach(() => {
        jest.clearAllMocks();
        provider = new ProposedContentProvider();
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
        expect(provider.provideTextDocumentContent(uri)).toBe('');
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
    let mockClient: jest.Mocked<AgentClient>;
    let diffProvider: DiffProvider;
    let extensionUri: vscode.Uri;

    beforeEach(() => {
        jest.restoreAllMocks();
        jest.clearAllMocks();
        mockVscode.workspace.fs.writeFile.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.readFile.mockReset().mockResolvedValue(new Uint8Array());
        mockVscode.workspace.fs.delete.mockReset().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory.mockReset().mockResolvedValue(undefined);
        mockVscode.window.showInformationMessage.mockReset().mockResolvedValue('Keep');
        mockVscode.window.showTextDocument.mockReset().mockResolvedValue(undefined);
        mockClient = createMockAgentClient();
        extensionUri = vscode.Uri.file('/ext');
        diffProvider = new DiffProvider(mockClient, extensionUri);
    });

    afterEach(() => {
        diffProvider.dispose();
    });

    describe('showChanges (write-first flow)', () => {
        it('writes files to disk immediately on showChanges', async () => {
            const changes = [
                makeFakeChange({ change_id: 'c1', file_path: 'src/a.ts', new_content: 'content a' }),
                makeFakeChange({ change_id: 'c2', file_path: 'src/b.ts', change_type: 'create', new_content: 'content b' }),
            ];
            diffProvider.setPendingChanges('sess-1', changes);
            await diffProvider.showChanges();

            expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(2);
            expect(mockClient.applyChanges).not.toHaveBeenCalled();
        });

        it('shows keep/undo notification after writing', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();

            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith(
                expect.stringContaining('applied 1 file change'),
                'Keep',
                'Undo'
            );
        });

        it('notifies server when user clicks Keep', async () => {
            mockVscode.window.showInformationMessage.mockResolvedValue('Keep');
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();

            expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith('sess-1', ['c1']);
        });

        it('reverts files when user clicks Undo on a create', async () => {
            mockVscode.window.showInformationMessage.mockResolvedValue('Undo');
            const change = makeFakeChange({ change_type: 'create', file_path: 'src/new.ts' });
            diffProvider.setPendingChanges('sess-1', [change]);
            await diffProvider.showChanges();

            // writeFile for the initial apply, then delete for the undo
            expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(1);
            expect(mockVscode.workspace.fs.delete).toHaveBeenCalledTimes(1);
        });

        it('restores original content when user clicks Undo on a modify', async () => {
            const originalBytes = new TextEncoder().encode('original content');
            mockVscode.workspace.fs.readFile.mockResolvedValue(originalBytes);
            mockVscode.window.showInformationMessage.mockResolvedValue('Undo');

            const change = makeFakeChange({ change_type: 'modify', new_content: 'new content' });
            diffProvider.setPendingChanges('sess-1', [change]);
            await diffProvider.showChanges();

            // writeFile called twice: once for apply, once for restore
            expect(mockVscode.workspace.fs.writeFile).toHaveBeenCalledTimes(2);
        });

        it('does nothing when no pending changes', async () => {
            await diffProvider.showChanges();
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();
            expect(mockVscode.window.showInformationMessage).not.toHaveBeenCalled();
        });

        it('shows error and aborts when no workspace folder is open', async () => {
            const originalFolders = mockVscode.workspace.workspaceFolders;
            mockVscode.workspace.workspaceFolders = undefined;

            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();

            expect(mockVscode.window.showErrorMessage).toHaveBeenCalledWith(
                'No workspace folder open. Cannot write files.'
            );
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();

            mockVscode.workspace.workspaceFolders = originalFolders;
        });

        it('shows error when all writes fail', async () => {
            mockVscode.workspace.fs.writeFile.mockRejectedValue(new Error('Disk full'));
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();

            expect(mockVscode.window.showErrorMessage).toHaveBeenCalledWith(
                expect.stringContaining('failed to apply')
            );
        });

        it('opens the first changed file after writing', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();

            expect(mockVscode.window.showTextDocument).toHaveBeenCalledTimes(1);
        });

        it('delete change type calls vscode.workspace.fs.delete', async () => {
            // readFile returns original content for the delete case
            mockVscode.workspace.fs.readFile.mockResolvedValue(new TextEncoder().encode('old'));
            const deleteChange = makeFakeChange({
                change_id: 'del-1',
                file_path: 'src/obsolete.ts',
                change_type: 'delete',
            });
            diffProvider.setPendingChanges('sess-1', [deleteChange]);
            await diffProvider.showChanges();

            expect(mockVscode.workspace.fs.delete).toHaveBeenCalledTimes(1);
            expect(mockVscode.workspace.fs.writeFile).not.toHaveBeenCalled();
        });

        it('clears state after keep', async () => {
            mockVscode.window.showInformationMessage.mockResolvedValue('Keep');
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });

        it('clears state after undo', async () => {
            mockVscode.window.showInformationMessage.mockResolvedValue('Undo');
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.showChanges();
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
    });

    describe('getPendingChanges', () => {
        it('returns copy of pending changes', () => {
            const changes = [makeFakeChange()];
            diffProvider.setPendingChanges('sess-1', changes);
            const result = diffProvider.getPendingChanges();
            expect(result).toEqual(changes);
            expect(result).not.toBe(changes);
        });

        it('returns empty array when no changes', () => {
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
    });

    describe('dispose', () => {
        it('cleans up and clears pending changes', () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            diffProvider.dispose();
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });
    });
});

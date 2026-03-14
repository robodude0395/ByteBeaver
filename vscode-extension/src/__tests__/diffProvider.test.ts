import * as vscode from 'vscode';
import { ProposedContentProvider, DiffProvider } from '../diffProvider';
import { AgentClient, FileChangeInfo } from '../agentClient';

// Mock agentClient module - we don't want the real one
jest.mock('../agentClient');

const mockVscode = vscode as any;

function createMockAgentClient(): jest.Mocked<AgentClient> {
    return {
        applyChanges: jest.fn(),
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
    let mockClient: jest.Mocked<AgentClient>;
    let diffProvider: DiffProvider;
    let extensionUri: vscode.Uri;

    beforeEach(() => {
        jest.clearAllMocks();
        mockClient = createMockAgentClient();
        extensionUri = vscode.Uri.file('/ext');
        diffProvider = new DiffProvider(mockClient, extensionUri);
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

            expect(mockVscode.commands.executeCommand).toHaveBeenCalledWith(
                'vscode.diff',
                expect.anything(),
                expect.anything(),
                'src/a.ts (Proposed Changes)'
            );
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

            expect(mockVscode.commands.executeCommand).toHaveBeenCalledWith(
                'vscode.diff',
                expect.anything(), // originalUri
                expect.anything(), // proposedUri
                'src/main.ts (Proposed Changes)'
            );

            // Verify the proposed URI uses the correct scheme
            const proposedUri = mockVscode.commands.executeCommand.mock.calls[0][2];
            expect(proposedUri.toString()).toContain('agent-proposed');
        });
    });

    describe('acceptChanges', () => {
        it('calls agentClient.applyChanges with correct IDs', async () => {
            mockClient.applyChanges.mockResolvedValue({
                applied: ['c1', 'c2'],
                failed: [],
                errors: {},
            });

            const changes = [
                makeFakeChange({ change_id: 'c1' }),
                makeFakeChange({ change_id: 'c2' }),
            ];
            diffProvider.setPendingChanges('sess-1', changes);

            await diffProvider.acceptChanges();

            expect(mockClient.applyChanges).toHaveBeenCalledWith('sess-1', ['c1', 'c2']);
        });

        it('shows success message and clears state', async () => {
            mockClient.applyChanges.mockResolvedValue({
                applied: ['c1'],
                failed: [],
                errors: {},
            });

            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();

            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith(
                'Applied 1 change(s) successfully.'
            );
            expect(diffProvider.getPendingChanges()).toEqual([]);
        });

        it('shows warning for failed changes', async () => {
            mockClient.applyChanges.mockResolvedValue({
                applied: [],
                failed: ['c1'],
                errors: { c1: 'write error' },
            });

            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();

            expect(mockVscode.window.showWarningMessage).toHaveBeenCalledWith(
                'Failed to apply changes: c1'
            );
        });

        it('shows error on network failure', async () => {
            mockClient.applyChanges.mockRejectedValue(new Error('Network error'));

            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);
            await diffProvider.acceptChanges();

            expect(mockVscode.window.showErrorMessage).toHaveBeenCalledWith(
                'Failed to apply changes: Network error'
            );
        });

        it('does nothing when no session or pending changes', async () => {
            await diffProvider.acceptChanges();
            expect(mockClient.applyChanges).not.toHaveBeenCalled();
        });
    });

    describe('rejectChanges', () => {
        it('clears pending changes and shows message', async () => {
            diffProvider.setPendingChanges('sess-1', [makeFakeChange()]);

            await diffProvider.rejectChanges();

            expect(diffProvider.getPendingChanges()).toEqual([]);
            expect(mockVscode.window.showInformationMessage).toHaveBeenCalledWith(
                'All proposed changes have been rejected.'
            );
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

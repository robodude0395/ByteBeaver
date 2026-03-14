import fc from 'fast-check';
import * as vscode from 'vscode';
import { DiffProvider } from '../diffProvider';
import { AgentClient, FileChangeInfo } from '../agentClient';

// Feature: client-side-file-writing (write-first / Copilot-style flow)

jest.mock('vscode');
jest.mock('../agentClient');

const mockVscode = vscode as any;

function createMockAgentClient(): jest.Mocked<AgentClient> {
    return {
        applyChanges: jest.fn(),
        notifyChangesApplied: jest.fn().mockResolvedValue(undefined),
        sendPrompt: jest.fn(),
        getStatus: jest.fn(),
        cancelSession: jest.fn(),
        healthCheck: jest.fn(),
    } as unknown as jest.Mocked<AgentClient>;
}

function setupWorkspaceFolder(): void {
    mockVscode.workspace.workspaceFolders = [
        {
            uri: {
                toString: () => 'file:///workspace',
                scheme: 'file',
                path: '/workspace',
                fsPath: '/workspace',
            },
            name: 'workspace',
            index: 0,
        },
    ];
}

function setupDefaultMocks(): void {
    mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Keep');
    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);
}

const pathSegmentArb = fc.stringMatching(/^[a-z0-9]{1,10}$/);

const fileChangeInfoArb = fc.record({
    change_id: fc.uuid(),
    file_path: fc
        .array(pathSegmentArb, { minLength: 1, maxLength: 4 })
        .map((parts) => parts.join('/')),
    change_type: fc.constantFrom('create', 'modify', 'delete'),
    diff: fc.string({ minLength: 0, maxLength: 200 }),
    new_content: fc.string({ minLength: 0, maxLength: 200 }),
});

// Property 1: showChanges writes files immediately without calling applyChanges
describe('Property 1: Write-first bypasses server apply_changes', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('showChanges writes locally and never calls agentClient.applyChanges', async () => {
        await fc.assert(
            fc.asyncProperty(
                fc.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }),
                async (changes: FileChangeInfo[]) => {
                    const localWriteFile = jest.fn().mockResolvedValue(undefined);
                    const localDelete = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.writeFile = localWriteFile;
                    mockVscode.workspace.fs.delete = localDelete;
                    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Keep');
                    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                    const mockClient = createMockAgentClient();
                    const dp = new DiffProvider(mockClient, vscode.Uri.file('/ext'));
                    dp.setPendingChanges('sess', changes);
                    await dp.showChanges();

                    expect(mockClient.applyChanges).not.toHaveBeenCalled();
                    const createModify = changes.filter(c => c.change_type !== 'delete').length;
                    const deletes = changes.filter(c => c.change_type === 'delete').length;
                    expect(localWriteFile).toHaveBeenCalledTimes(createModify);
                    expect(localDelete).toHaveBeenCalledTimes(deletes);
                    dp.dispose();
                }
            ),
            { numRuns: 100 }
        );
    });
});

// Property 2: File paths resolve against workspace root
describe('Property 2: File paths resolve against workspace root', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('URI passed to writeFile/delete equals Uri.joinPath(workspaceRoot, file_path)', async () => {
        await fc.assert(
            fc.asyncProperty(fileChangeInfoArb, async (change: FileChangeInfo) => {
                const localWriteFile = jest.fn().mockResolvedValue(undefined);
                const localDelete = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.writeFile = localWriteFile;
                mockVscode.workspace.fs.delete = localDelete;
                mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Keep');
                mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);
                mockVscode.Uri.joinPath.mockClear();

                const root = mockVscode.workspace.workspaceFolders[0].uri;
                const mockClient = createMockAgentClient();
                const dp = new DiffProvider(mockClient, vscode.Uri.file('/ext'));
                dp.setPendingChanges('sess', [change]);
                await dp.showChanges();

                expect(mockVscode.Uri.joinPath).toHaveBeenCalledWith(root, change.file_path);
                const expected = `${root.toString()}/${change.file_path}`;
                if (change.change_type === 'delete') {
                    expect(localDelete.mock.calls[0][0].toString()).toBe(expected);
                } else {
                    expect(localWriteFile.mock.calls[0][0].toString()).toBe(expected);
                }
                dp.dispose();
            }),
            { numRuns: 100 }
        );
    });
});

// Property 3: Create/modify uses new_content (or diff fallback)
describe('Property 3: Create and modify writes use new_content', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('writeFile is called with new_content encoded as Uint8Array', async () => {
        const createModifyArb = fileChangeInfoArb.filter(c => c.change_type !== 'delete');
        await fc.assert(
            fc.asyncProperty(createModifyArb, async (change: FileChangeInfo) => {
                const localWriteFile = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.writeFile = localWriteFile;
                mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Keep');
                mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                const dp = new DiffProvider(createMockAgentClient(), vscode.Uri.file('/ext'));
                dp.setPendingChanges('sess', [change]);
                await dp.showChanges();

                expect(localWriteFile).toHaveBeenCalledTimes(1);
                const written = localWriteFile.mock.calls[0][1];
                const expectedContent = change.new_content ?? change.diff;
                expect(written).toEqual(new TextEncoder().encode(expectedContent));
                dp.dispose();
            }),
            { numRuns: 100 }
        );
    });
});

// Property 4: Undo on create deletes the file
describe('Property 4: Undo reverts created files by deleting them', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('undo after create calls delete', async () => {
        const createArb = fileChangeInfoArb.filter(c => c.change_type === 'create');
        await fc.assert(
            fc.asyncProperty(createArb, async (change: FileChangeInfo) => {
                const localWriteFile = jest.fn().mockResolvedValue(undefined);
                const localDelete = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.writeFile = localWriteFile;
                mockVscode.workspace.fs.delete = localDelete;
                mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                mockVscode.workspace.fs.readFile = jest.fn().mockRejectedValue(new Error('not found'));
                mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Undo');
                mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                const dp = new DiffProvider(createMockAgentClient(), vscode.Uri.file('/ext'));
                dp.setPendingChanges('sess', [change]);
                await dp.showChanges();

                // writeFile for apply, delete for undo
                expect(localWriteFile).toHaveBeenCalledTimes(1);
                expect(localDelete).toHaveBeenCalledTimes(1);
                dp.dispose();
            }),
            { numRuns: 100 }
        );
    });
});

// Property 5: Undo on modify restores original content
describe('Property 5: Undo restores original content for modified files', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('undo after modify writes back original bytes', async () => {
        const modifyArb = fileChangeInfoArb.filter(c => c.change_type === 'modify');
        await fc.assert(
            fc.asyncProperty(
                modifyArb,
                fc.string({ minLength: 1, maxLength: 200 }),
                async (change: FileChangeInfo, originalStr: string) => {
                    const originalBytes = new TextEncoder().encode(originalStr);
                    const localWriteFile = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.writeFile = localWriteFile;
                    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(originalBytes);
                    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Undo');
                    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                    const dp = new DiffProvider(createMockAgentClient(), vscode.Uri.file('/ext'));
                    dp.setPendingChanges('sess', [change]);
                    await dp.showChanges();

                    // writeFile called twice: apply + restore
                    expect(localWriteFile).toHaveBeenCalledTimes(2);
                    // Second call should restore original bytes
                    expect(localWriteFile.mock.calls[1][1]).toEqual(originalBytes);
                    dp.dispose();
                }
            ),
            { numRuns: 100 }
        );
    });
});

// Property 6: Keep notifies server with applied change IDs
describe('Property 6: Keep notifies server with applied change IDs', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('notifyChangesApplied called with all IDs on Keep', async () => {
        await fc.assert(
            fc.asyncProperty(
                fc.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }),
                async (changes: FileChangeInfo[]) => {
                    mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Keep');
                    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                    const mockClient = createMockAgentClient();
                    const dp = new DiffProvider(mockClient, vscode.Uri.file('/ext'));
                    dp.setPendingChanges('sess', changes);
                    await dp.showChanges();

                    const expectedIds = changes.map(c => c.change_id);
                    expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith('sess', expectedIds);
                    dp.dispose();
                }
            ),
            { numRuns: 100 }
        );
    });
});

// Property 7: Undo does NOT notify server
describe('Property 7: Undo does not notify server', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('notifyChangesApplied is not called on Undo', async () => {
        await fc.assert(
            fc.asyncProperty(
                fc.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }),
                async (changes: FileChangeInfo[]) => {
                    mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue('Undo');
                    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                    const mockClient = createMockAgentClient();
                    const dp = new DiffProvider(mockClient, vscode.Uri.file('/ext'));
                    dp.setPendingChanges('sess', changes);
                    await dp.showChanges();

                    expect(mockClient.notifyChangesApplied).not.toHaveBeenCalled();
                    dp.dispose();
                }
            ),
            { numRuns: 100 }
        );
    });
});

// Property 8: State is cleared after both Keep and Undo
describe('Property 8: State cleared after Keep or Undo', () => {
    beforeEach(() => { jest.clearAllMocks(); setupWorkspaceFolder(); setupDefaultMocks(); });

    it('pendingChanges is empty after showChanges completes', async () => {
        await fc.assert(
            fc.asyncProperty(
                fc.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }),
                fc.constantFrom('Keep', 'Undo'),
                async (changes: FileChangeInfo[], choice: string) => {
                    mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
                    mockVscode.workspace.fs.readFile = jest.fn().mockResolvedValue(new Uint8Array());
                    mockVscode.window.showInformationMessage = jest.fn().mockResolvedValue(choice);
                    mockVscode.window.showTextDocument = jest.fn().mockResolvedValue(undefined);

                    const dp = new DiffProvider(createMockAgentClient(), vscode.Uri.file('/ext'));
                    dp.setPendingChanges('sess', changes);
                    await dp.showChanges();

                    expect(dp.getPendingChanges()).toEqual([]);
                    dp.dispose();
                }
            ),
            { numRuns: 100 }
        );
    });
});

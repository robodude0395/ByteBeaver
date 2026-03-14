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
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const fast_check_1 = __importDefault(require("fast-check"));
const vscode = __importStar(require("vscode"));
const diffProvider_1 = require("../diffProvider");
// Feature: client-side-file-writing, Property 1: Local writes bypass server apply_changes
jest.mock('vscode');
jest.mock('../agentClient');
const mockVscode = vscode;
function createMockAgentClient() {
    return {
        applyChanges: jest.fn(),
        notifyChangesApplied: jest.fn().mockResolvedValue(undefined),
        sendPrompt: jest.fn(),
        getStatus: jest.fn(),
        cancelSession: jest.fn(),
        healthCheck: jest.fn(),
    };
}
function setupWorkspaceFolder() {
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
const pathSegmentArb = fast_check_1.default.stringMatching(/^[a-z0-9]{1,10}$/);
const fileChangeInfoArb = fast_check_1.default.record({
    change_id: fast_check_1.default.uuid(),
    file_path: fast_check_1.default
        .array(pathSegmentArb, { minLength: 1, maxLength: 4 })
        .map((parts) => parts.join('/')),
    change_type: fast_check_1.default.constantFrom('create', 'modify', 'delete'),
    diff: fast_check_1.default.string({ minLength: 0, maxLength: 200 }),
});
describe('Property 1: Local writes bypass server apply_changes', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile.mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete.mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory.mockResolvedValue(undefined);
    });
    /**
     * Property 1: For any set of pending changes, acceptChanges() calls
     * vscode.workspace.fs.writeFile/delete and never calls agentClient.applyChanges.
     *
     * Validates: Requirements 1.1
     */
    it('acceptChanges writes locally and never calls agentClient.applyChanges', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', changes);
            await diffProvider.acceptChanges();
            expect(mockClient.applyChanges).not.toHaveBeenCalled();
            const createModifyCount = changes.filter((c) => c.change_type === 'create' || c.change_type === 'modify').length;
            const deleteCount = changes.filter((c) => c.change_type === 'delete').length;
            expect(localWriteFile).toHaveBeenCalledTimes(createModifyCount);
            expect(localDelete).toHaveBeenCalledTimes(deleteCount);
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 2: File paths resolve against workspace root
describe('Property 2: File paths resolve against workspace root', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        // Reassign fresh jest.fn() instances to avoid stale references from other tests
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 2: For any FileChangeInfo with a relative file_path, the URI
     * passed to writeFile/delete equals Uri.joinPath(workspaceRoot, file_path).
     *
     * Validates: Requirements 1.2, 5.2
     */
    it('URI passed to writeFile/delete equals Uri.joinPath(workspaceRoot, file_path)', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fileChangeInfoArb, async (change) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            mockVscode.Uri.joinPath.mockClear();
            const workspaceRoot = mockVscode.workspace.workspaceFolders[0].uri;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', [change]);
            await diffProvider.acceptChanges();
            // Uri.joinPath should have been called with workspace root and file_path
            expect(mockVscode.Uri.joinPath).toHaveBeenCalledWith(workspaceRoot, change.file_path);
            // Expected URI string from the mock's joinPath implementation
            const expectedUriStr = `${workspaceRoot.toString()}/${change.file_path}`;
            if (change.change_type === 'delete') {
                expect(localDelete).toHaveBeenCalledTimes(1);
                expect(localDelete.mock.calls[0][0].toString()).toBe(expectedUriStr);
            }
            else {
                expect(localWriteFile).toHaveBeenCalledTimes(1);
                expect(localWriteFile.mock.calls[0][0].toString()).toBe(expectedUriStr);
            }
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 3: Create and modify writes use diff content
describe('Property 3: Create and modify writes use diff content', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 3: For any FileChangeInfo with change_type "create" or "modify",
     * writeFile is called with the diff field encoded as Uint8Array via TextEncoder.
     *
     * Validates: Requirements 1.3, 1.4
     */
    it('writeFile is called with diff content encoded as Uint8Array', async () => {
        const createModifyArb = fileChangeInfoArb.filter((c) => c.change_type === 'create' || c.change_type === 'modify');
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(createModifyArb, async (change) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', [change]);
            await diffProvider.acceptChanges();
            // writeFile should have been called exactly once
            expect(localWriteFile).toHaveBeenCalledTimes(1);
            // The second argument should be the diff encoded as Uint8Array
            const writtenContent = localWriteFile.mock.calls[0][1];
            const expectedContent = new TextEncoder().encode(change.diff);
            expect(writtenContent).toEqual(expectedContent);
            // delete should not have been called for create/modify
            expect(localDelete).not.toHaveBeenCalled();
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 4: Delete removes the file
describe('Property 4: Delete removes the file', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 4: For any FileChangeInfo with change_type "delete",
     * vscode.workspace.fs.delete is called with the resolved URI
     * (Uri.joinPath(workspaceRoot, file_path)), and writeFile is NOT called.
     *
     * Validates: Requirements 1.5
     */
    it('delete calls vscode.workspace.fs.delete with resolved URI and never calls writeFile', async () => {
        const deleteArb = fileChangeInfoArb.filter((c) => c.change_type === 'delete');
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(deleteArb, async (change) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const workspaceRoot = mockVscode.workspace.workspaceFolders[0].uri;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', [change]);
            await diffProvider.acceptChanges();
            // delete should have been called exactly once
            expect(localDelete).toHaveBeenCalledTimes(1);
            // The URI passed to delete should be the resolved path
            const expectedUriStr = `${workspaceRoot.toString()}/${change.file_path}`;
            expect(localDelete.mock.calls[0][0].toString()).toBe(expectedUriStr);
            // writeFile should NOT have been called for delete changes
            expect(localWriteFile).not.toHaveBeenCalled();
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 5: Parent directories are created for nested paths
describe('Property 5: Parent directories are created for nested paths', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 5: For any FileChangeInfo with directory separators in file_path,
     * createDirectory is called with the parent directory URI before writeFile is called.
     *
     * Validates: Requirements 2.1
     */
    it('createDirectory is called with parent URI before writeFile for nested paths', async () => {
        const nestedCreateModifyArb = fileChangeInfoArb.filter((c) => (c.change_type === 'create' || c.change_type === 'modify') &&
            c.file_path.includes('/'));
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(nestedCreateModifyArb, async (change) => {
            // Track call order to verify createDirectory is called before writeFile
            const callOrder = [];
            const localCreateDir = jest.fn().mockImplementation(async () => {
                callOrder.push('createDirectory');
            });
            const localWriteFile = jest.fn().mockImplementation(async () => {
                callOrder.push('writeFile');
            });
            const localDelete = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            const workspaceRoot = mockVscode.workspace.workspaceFolders[0].uri;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', [change]);
            await diffProvider.acceptChanges();
            // createDirectory should have been called exactly once
            expect(localCreateDir).toHaveBeenCalledTimes(1);
            // Derive the expected parent URI from the resolved file URI
            const resolvedUriStr = `${workspaceRoot.toString()}/${change.file_path}`;
            const lastSlash = resolvedUriStr.lastIndexOf('/');
            const parentPath = resolvedUriStr.substring(0, lastSlash);
            // ensureParentDirectories uses Uri.parse(`${scheme}://${parentPath}`)
            const expectedParentUriStr = `file://${parentPath}`;
            expect(localCreateDir.mock.calls[0][0].toString()).toBe(expectedParentUriStr);
            // writeFile should have been called exactly once
            expect(localWriteFile).toHaveBeenCalledTimes(1);
            // createDirectory must be called before writeFile
            expect(callOrder).toEqual(['createDirectory', 'writeFile']);
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 9: Content round-trip fidelity
describe('Property 9: Content round-trip fidelity', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 9: For any valid FileChangeInfo with change_type "create" or "modify",
     * the bytes passed to vscode.workspace.fs.writeFile should decode to a string
     * identical to the diff field. That is:
     * new TextDecoder().decode(writtenContent) === change.diff
     *
     * Validates: Requirements 6.1, 6.2, 6.3
     */
    it('content written to writeFile round-trips back to the original diff string', async () => {
        const createModifyArb = fileChangeInfoArb.filter((c) => c.change_type === 'create' || c.change_type === 'modify');
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(createModifyArb, async (change) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('test-session', [change]);
            await diffProvider.acceptChanges();
            // writeFile should have been called exactly once
            expect(localWriteFile).toHaveBeenCalledTimes(1);
            // Extract the Uint8Array passed to writeFile and decode it back
            const writtenContent = localWriteFile.mock.calls[0][1];
            const decodedContent = new TextDecoder().decode(writtenContent);
            // Round-trip fidelity: decoded content must equal original diff
            expect(decodedContent).toBe(change.diff);
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 6: Server is notified with applied change IDs
describe('Property 6: Server is notified with applied change IDs', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 6: For any batch where all writes succeed,
     * notifyChangesApplied is called with the session ID and all change IDs.
     *
     * Validates: Requirements 3.1
     */
    it('notifyChangesApplied is called with all change IDs when all writes succeed', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            const sessionId = 'session-all-success';
            diffProvider.setPendingChanges(sessionId, changes);
            await diffProvider.acceptChanges();
            const expectedIds = changes.map((c) => c.change_id);
            expect(mockClient.notifyChangesApplied).toHaveBeenCalledTimes(1);
            expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith(sessionId, expectedIds);
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
    /**
     * Property 6 (partial failure): For any batch where some writes fail,
     * notifyChangesApplied is called with only the successful change IDs.
     *
     * Validates: Requirements 3.1
     */
    it('notifyChangesApplied is called with only successful change IDs on partial failure', async () => {
        // Generate batches of at least 2 changes so we can have both successes and failures
        const batchArb = fast_check_1.default.array(fileChangeInfoArb, { minLength: 2, maxLength: 10 });
        // For each batch, generate a non-empty, non-full set of failure indices
        const batchWithFailuresArb = batchArb.chain((changes) => fast_check_1.default
            .subarray(changes.map((_, i) => i), { minLength: 1, maxLength: changes.length - 1 })
            .map((failIndices) => ({ changes, failIndices: new Set(failIndices) })));
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(batchWithFailuresArb, async ({ changes, failIndices }) => {
            let writeCallIndex = 0;
            let deleteCallIndex = 0;
            // Track which change index we're processing to decide success/failure
            // We need to map fs calls back to change indices
            // Since changes are processed in order, we track by change index
            const localWriteFile = jest.fn().mockImplementation(async () => {
                // Find which change this write corresponds to
                const createModifyChanges = changes.filter((c) => c.change_type === 'create' || c.change_type === 'modify');
                const changeIdx = changes.indexOf(createModifyChanges[writeCallIndex]);
                writeCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Write failed');
                }
            });
            const localDelete = jest.fn().mockImplementation(async () => {
                const deleteChanges = changes.filter((c) => c.change_type === 'delete');
                const changeIdx = changes.indexOf(deleteChanges[deleteCallIndex]);
                deleteCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Delete failed');
                }
            });
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            const sessionId = 'session-partial-fail';
            diffProvider.setPendingChanges(sessionId, changes);
            await diffProvider.acceptChanges();
            // Compute expected successful change IDs
            const expectedSuccessIds = changes
                .filter((_, i) => !failIndices.has(i))
                .map((c) => c.change_id);
            if (expectedSuccessIds.length > 0) {
                expect(mockClient.notifyChangesApplied).toHaveBeenCalledTimes(1);
                expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith(sessionId, expectedSuccessIds);
            }
            else {
                expect(mockClient.notifyChangesApplied).not.toHaveBeenCalled();
            }
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 7: Partial failures do not abort the batch
describe('Property 7: Partial failures do not abort the batch', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 7: For any batch of N changes where K fail (1 <= K < N),
     * all N are attempted (total writeFile + delete calls = N) and N-K succeed.
     * The batch is NOT aborted early.
     *
     * Validates: Requirements 4.2
     */
    it('all N changes are attempted and N-K succeed even when K fail', async () => {
        const batchArb = fast_check_1.default.array(fileChangeInfoArb, { minLength: 2, maxLength: 10 });
        const batchWithFailuresArb = batchArb.chain((changes) => fast_check_1.default
            .subarray(changes.map((_, i) => i), { minLength: 1, maxLength: changes.length - 1 })
            .map((failIndices) => ({ changes, failIndices: new Set(failIndices) })));
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(batchWithFailuresArb, async ({ changes, failIndices }) => {
            let writeCallIndex = 0;
            let deleteCallIndex = 0;
            const localWriteFile = jest.fn().mockImplementation(async () => {
                const createModifyChanges = changes.filter((c) => c.change_type === 'create' || c.change_type === 'modify');
                const changeIdx = changes.indexOf(createModifyChanges[writeCallIndex]);
                writeCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Write failed');
                }
            });
            const localDelete = jest.fn().mockImplementation(async () => {
                const deleteChanges = changes.filter((c) => c.change_type === 'delete');
                const changeIdx = changes.indexOf(deleteChanges[deleteCallIndex]);
                deleteCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Delete failed');
                }
            });
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('session-partial', changes);
            await diffProvider.acceptChanges();
            const N = changes.length;
            const K = failIndices.size;
            // All N changes must be attempted: total writeFile + delete calls = N
            const totalCalls = localWriteFile.mock.calls.length + localDelete.mock.calls.length;
            expect(totalCalls).toBe(N);
            // Count how many writeFile/delete calls did NOT throw
            // Successful calls = those for changes whose index is NOT in failIndices
            const expectedSuccessCount = N - K;
            // Verify via the notification: only successful change IDs are notified
            const expectedSuccessIds = changes
                .filter((_, i) => !failIndices.has(i))
                .map((c) => c.change_id);
            if (expectedSuccessIds.length > 0) {
                expect(mockClient.notifyChangesApplied).toHaveBeenCalledTimes(1);
                expect(mockClient.notifyChangesApplied).toHaveBeenCalledWith('session-partial', expectedSuccessIds);
                // The number of successful IDs should be N-K
                expect(expectedSuccessIds.length).toBe(expectedSuccessCount);
            }
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 8: Summary message reflects actual counts
describe('Property 8: Summary message reflects actual counts', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 8 (all succeed): For any batch with S successes and 0 failures,
     * showInformationMessage is called with a message containing the success count S.
     *
     * Validates: Requirements 4.3
     */
    it('all succeed: showInformationMessage contains the success count', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const localShowInfo = jest.fn();
            const localShowWarning = jest.fn();
            const localShowError = jest.fn();
            mockVscode.window.showInformationMessage = localShowInfo;
            mockVscode.window.showWarningMessage = localShowWarning;
            mockVscode.window.showErrorMessage = localShowError;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('session-all-ok', changes);
            await diffProvider.acceptChanges();
            const S = changes.length;
            expect(localShowInfo).toHaveBeenCalledTimes(1);
            const message = localShowInfo.mock.calls[0][0];
            expect(message).toContain(String(S));
            expect(localShowWarning).not.toHaveBeenCalled();
            expect(localShowError).not.toHaveBeenCalled();
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
    /**
     * Property 8 (partial failure): For any batch with S successes and F failures
     * (S > 0, F > 0), showWarningMessage is called with a message containing both
     * the success count S and the failure count F.
     *
     * Validates: Requirements 4.3
     */
    it('partial failure: showWarningMessage contains both success and failure counts', async () => {
        const batchArb = fast_check_1.default.array(fileChangeInfoArb, { minLength: 2, maxLength: 10 });
        const batchWithFailuresArb = batchArb.chain((changes) => fast_check_1.default
            .subarray(changes.map((_, i) => i), { minLength: 1, maxLength: changes.length - 1 })
            .map((failIndices) => ({ changes, failIndices: new Set(failIndices) })));
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(batchWithFailuresArb, async ({ changes, failIndices }) => {
            let writeCallIndex = 0;
            let deleteCallIndex = 0;
            const localWriteFile = jest.fn().mockImplementation(async () => {
                const createModifyChanges = changes.filter((c) => c.change_type === 'create' || c.change_type === 'modify');
                const changeIdx = changes.indexOf(createModifyChanges[writeCallIndex]);
                writeCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Write failed');
                }
            });
            const localDelete = jest.fn().mockImplementation(async () => {
                const deleteChanges = changes.filter((c) => c.change_type === 'delete');
                const changeIdx = changes.indexOf(deleteChanges[deleteCallIndex]);
                deleteCallIndex++;
                if (failIndices.has(changeIdx)) {
                    throw new Error('Delete failed');
                }
            });
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const localShowInfo = jest.fn();
            const localShowWarning = jest.fn();
            const localShowError = jest.fn();
            mockVscode.window.showInformationMessage = localShowInfo;
            mockVscode.window.showWarningMessage = localShowWarning;
            mockVscode.window.showErrorMessage = localShowError;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('session-partial', changes);
            await diffProvider.acceptChanges();
            const S = changes.length - failIndices.size;
            const F = failIndices.size;
            if (S > 0 && F > 0) {
                expect(localShowWarning).toHaveBeenCalledTimes(1);
                const message = localShowWarning.mock.calls[0][0];
                expect(message).toContain(String(S));
                expect(message).toContain(String(F));
                expect(localShowInfo).not.toHaveBeenCalled();
                expect(localShowError).not.toHaveBeenCalled();
            }
            // If S === 0, all failed → showErrorMessage (covered by all-fail case)
            // If F === 0, all succeeded → showInformationMessage (covered by all-succeed case)
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
    /**
     * Property 8 (all fail): For any batch where all writes fail (S = 0, F > 0),
     * showErrorMessage is called.
     *
     * Validates: Requirements 4.3
     */
    it('all fail: showErrorMessage is called', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            const localWriteFile = jest.fn().mockRejectedValue(new Error('Write failed'));
            const localDelete = jest.fn().mockRejectedValue(new Error('Delete failed'));
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const localShowInfo = jest.fn();
            const localShowWarning = jest.fn();
            const localShowError = jest.fn();
            mockVscode.window.showInformationMessage = localShowInfo;
            mockVscode.window.showWarningMessage = localShowWarning;
            mockVscode.window.showErrorMessage = localShowError;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            diffProvider.setPendingChanges('session-all-fail', changes);
            await diffProvider.acceptChanges();
            const F = changes.length;
            expect(localShowError).toHaveBeenCalledTimes(1);
            const message = localShowError.mock.calls[0][0];
            expect(message).toContain(String(F));
            expect(localShowInfo).not.toHaveBeenCalled();
            expect(localShowWarning).not.toHaveBeenCalled();
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 10: Reject clears state without writing
describe('Property 10: Reject clears state without writing', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 10: For any set of pending changes, calling rejectChanges()
     * clears state (getPendingChanges() returns []), hides status bar buttons,
     * and makes zero calls to vscode.workspace.fs.writeFile or delete.
     *
     * Validates: Requirements 7.3
     */
    it('rejectChanges clears pending changes, hides buttons, and never writes or deletes', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            // Set pending changes (this also creates and shows status bar buttons)
            diffProvider.setPendingChanges('test-session', changes);
            // Capture references to the status bar button mocks created by setPendingChanges
            const createStatusBarItemMock = mockVscode.window.createStatusBarItem;
            const statusBarItems = createStatusBarItemMock.mock.results.map((r) => r.value);
            // Reject changes
            await diffProvider.rejectChanges();
            // getPendingChanges() should return an empty array
            expect(diffProvider.getPendingChanges()).toEqual([]);
            // writeFile should never have been called
            expect(localWriteFile).not.toHaveBeenCalled();
            // delete should never have been called
            expect(localDelete).not.toHaveBeenCalled();
            // Status bar buttons should have hide() called
            // setPendingChanges -> showChangeActions creates 2 status bar items
            expect(statusBarItems.length).toBeGreaterThanOrEqual(2);
            for (const item of statusBarItems) {
                expect(item.hide).toHaveBeenCalled();
            }
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
// Feature: client-side-file-writing, Property 11: Accept clears state after writing
describe('Property 11: Accept clears state after writing', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupWorkspaceFolder();
        mockVscode.workspace.fs.writeFile = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
        mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    });
    /**
     * Property 11: For any set of pending changes, after acceptChanges() completes,
     * getPendingChanges() returns an empty array and status bar buttons are hidden.
     *
     * Validates: Requirements 7.4
     */
    it('acceptChanges clears pending changes and hides status bar buttons', async () => {
        await fast_check_1.default.assert(fast_check_1.default.asyncProperty(fast_check_1.default.array(fileChangeInfoArb, { minLength: 1, maxLength: 10 }), async (changes) => {
            // Use per-iteration local mocks to avoid cross-iteration leakage
            const localWriteFile = jest.fn().mockResolvedValue(undefined);
            const localDelete = jest.fn().mockResolvedValue(undefined);
            const localCreateDir = jest.fn().mockResolvedValue(undefined);
            mockVscode.workspace.fs.writeFile = localWriteFile;
            mockVscode.workspace.fs.delete = localDelete;
            mockVscode.workspace.fs.createDirectory = localCreateDir;
            const mockClient = createMockAgentClient();
            const diffProvider = new diffProvider_1.DiffProvider(mockClient, vscode.Uri.file('/ext'));
            // Set pending changes (this also creates and shows status bar buttons)
            diffProvider.setPendingChanges('test-session', changes);
            // Capture references to the status bar button mocks created by setPendingChanges
            const createStatusBarItemMock = mockVscode.window.createStatusBarItem;
            const statusBarItems = createStatusBarItemMock.mock.results.map((r) => r.value);
            // Accept changes
            await diffProvider.acceptChanges();
            // getPendingChanges() should return an empty array
            expect(diffProvider.getPendingChanges()).toEqual([]);
            // Status bar buttons should have hide() called
            // setPendingChanges -> showChangeActions creates 2 status bar items
            expect(statusBarItems.length).toBeGreaterThanOrEqual(2);
            for (const item of statusBarItems) {
                expect(item.hide).toHaveBeenCalled();
            }
            diffProvider.dispose();
        }), { numRuns: 100 });
    });
});
//# sourceMappingURL=diffProvider.property.test.js.map
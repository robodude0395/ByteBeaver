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
jest.mock('vscode');
jest.mock('../agentClient');
const mockVscode = vscode;
test('local mock replacement visible to DiffProvider', async () => {
    mockVscode.workspace.workspaceFolders = [{
            uri: { toString: () => 'file:///workspace', scheme: 'file',
                path: '/workspace', fsPath: '/workspace' },
            name: 'workspace', index: 0,
        }];
    const localWF = jest.fn().mockResolvedValue(undefined);
    mockVscode.workspace.fs.writeFile = localWF;
    mockVscode.workspace.fs.delete = jest.fn().mockResolvedValue(undefined);
    mockVscode.workspace.fs.createDirectory = jest.fn().mockResolvedValue(undefined);
    const client = {
        applyChanges: jest.fn(),
        notifyChangesApplied: jest.fn().mockResolvedValue(undefined),
        sendPrompt: jest.fn(), getStatus: jest.fn(),
        cancelSession: jest.fn(), healthCheck: jest.fn(),
    };
    const dp = new diffProvider_1.DiffProvider(client, vscode.Uri.file('/ext'));
    dp.setPendingChanges('s', [
        { change_id: 'c1', file_path: 'test.txt',
            change_type: 'create', diff: 'hello' }
    ]);
    await dp.acceptChanges();
    console.log('localWF calls:', localWF.mock.calls.length);
    console.log('same ref?', mockVscode.workspace.fs.writeFile === localWF);
    expect(localWF).toHaveBeenCalledTimes(1);
    dp.dispose();
});
//# sourceMappingURL=debug_write.test.js.map
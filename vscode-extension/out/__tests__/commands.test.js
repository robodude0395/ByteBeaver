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
const commands_1 = require("../commands");
/**
 * Unit tests for slash commands.
 * Validates: Requirements 13.5
 */
describe('parseSlashCommand', () => {
    it("parses '/agent build some project'", () => {
        const result = (0, commands_1.parseSlashCommand)('/agent build some project');
        expect(result).toEqual({ commandName: '/agent build', args: 'some project' });
    });
    it("parses '/agent implement user auth'", () => {
        const result = (0, commands_1.parseSlashCommand)('/agent implement user auth');
        expect(result).toEqual({ commandName: '/agent implement', args: 'user auth' });
    });
    it("parses '/agent refactor the login module'", () => {
        const result = (0, commands_1.parseSlashCommand)('/agent refactor the login module');
        expect(result).toEqual({ commandName: '/agent refactor', args: 'the login module' });
    });
    it("parses '/agent explain this function'", () => {
        const result = (0, commands_1.parseSlashCommand)('/agent explain this function');
        expect(result).toEqual({ commandName: '/agent explain', args: 'this function' });
    });
    it("parses '/agent build' with no args", () => {
        const result = (0, commands_1.parseSlashCommand)('/agent build');
        expect(result).toEqual({ commandName: '/agent build', args: '' });
    });
    it("returns null for 'hello world' (no slash)", () => {
        expect((0, commands_1.parseSlashCommand)('hello world')).toBeNull();
    });
    it("returns null for '/unknown command'", () => {
        expect((0, commands_1.parseSlashCommand)('/unknown command')).toBeNull();
    });
    it("returns null for '/agentbuild' (no space after agent)", () => {
        expect((0, commands_1.parseSlashCommand)('/agentbuild')).toBeNull();
    });
});
describe('handleSlashCommand', () => {
    it("returns matched:true and expanded prompt for '/agent build a REST API'", () => {
        const result = (0, commands_1.handleSlashCommand)('/agent build a REST API');
        expect(result.matched).toBe(true);
        expect(result.prompt).toBe('Build the project: a REST API');
    });
    it("returns matched:true for '/agent implement' with empty args", () => {
        const result = (0, commands_1.handleSlashCommand)('/agent implement');
        expect(result.matched).toBe(true);
        expect(result.prompt).toBe('Implement the following feature: ');
    });
    it('returns matched:false and original input for regular text', () => {
        const result = (0, commands_1.handleSlashCommand)('just some regular text');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('just some regular text');
    });
    it('returns matched:false for unrecognized slash commands', () => {
        const result = (0, commands_1.handleSlashCommand)('/unknown do something');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('/unknown do something');
    });
});
describe('SLASH_COMMANDS', () => {
    it('contains exactly 4 commands', () => {
        expect(commands_1.SLASH_COMMANDS).toHaveLength(4);
    });
    it('all commands have name, command, description, promptTemplate fields', () => {
        for (const cmd of commands_1.SLASH_COMMANDS) {
            expect(cmd).toHaveProperty('name');
            expect(cmd).toHaveProperty('command');
            expect(cmd).toHaveProperty('description');
            expect(cmd).toHaveProperty('promptTemplate');
            expect(typeof cmd.name).toBe('string');
            expect(typeof cmd.command).toBe('string');
            expect(typeof cmd.description).toBe('string');
            expect(typeof cmd.promptTemplate).toBe('string');
        }
    });
    it("all prompt templates contain '{args}' placeholder", () => {
        for (const cmd of commands_1.SLASH_COMMANDS) {
            expect(cmd.promptTemplate).toContain('{args}');
        }
    });
});
describe('registerCommands', () => {
    const mockSendMessage = jest.fn();
    const mockChatPanel = { sendMessage: mockSendMessage };
    beforeEach(() => {
        jest.clearAllMocks();
    });
    it('registers a command for each slash command', () => {
        (0, commands_1.registerCommands)(mockChatPanel);
        expect(vscode.commands.registerCommand).toHaveBeenCalledTimes(commands_1.SLASH_COMMANDS.length);
        for (const cmd of commands_1.SLASH_COMMANDS) {
            expect(vscode.commands.registerCommand).toHaveBeenCalledWith(cmd.command, expect.any(Function));
        }
    });
    it('returns array of disposables', () => {
        const disposables = (0, commands_1.registerCommands)(mockChatPanel);
        expect(Array.isArray(disposables)).toBe(true);
        expect(disposables).toHaveLength(commands_1.SLASH_COMMANDS.length);
        for (const d of disposables) {
            expect(d).toHaveProperty('dispose');
        }
    });
});
describe('SlashCommandCompletionProvider', () => {
    const provider = new commands_1.SlashCommandCompletionProvider();
    function makeDocAndPos(lineText, cursorChar) {
        const pos = { line: 0, character: cursorChar ?? lineText.length };
        const doc = {
            lineAt: jest.fn().mockReturnValue({ text: lineText }),
        };
        return { doc, pos };
    }
    const token = {};
    const ctx = {};
    it("returns completion items when line contains '/'", () => {
        const { doc, pos } = makeDocAndPos('/ag');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        expect(items.length).toBe(commands_1.SLASH_COMMANDS.length);
    });
    it("returns empty array when line doesn't contain '/'", () => {
        const { doc, pos } = makeDocAndPos('hello world');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        expect(items).toHaveLength(0);
    });
    it('each completion item has correct label and detail', () => {
        const { doc, pos } = makeDocAndPos('/');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        for (let i = 0; i < commands_1.SLASH_COMMANDS.length; i++) {
            expect(items[i].label).toBe(commands_1.SLASH_COMMANDS[i].name);
            expect(items[i].detail).toBe(commands_1.SLASH_COMMANDS[i].description);
        }
    });
});
//# sourceMappingURL=commands.test.js.map
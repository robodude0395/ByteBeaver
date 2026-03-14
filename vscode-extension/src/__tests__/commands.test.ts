import * as vscode from 'vscode';
import {
    SLASH_COMMANDS,
    parseSlashCommand,
    handleSlashCommand,
    registerCommands,
    SlashCommandCompletionProvider,
} from '../commands';

/**
 * Unit tests for slash commands.
 * Validates: Requirements 13.5
 */

describe('parseSlashCommand', () => {
    it("parses '/agent build some project'", () => {
        const result = parseSlashCommand('/agent build some project');
        expect(result).toEqual({ commandName: '/agent build', args: 'some project' });
    });

    it("parses '/agent implement user auth'", () => {
        const result = parseSlashCommand('/agent implement user auth');
        expect(result).toEqual({ commandName: '/agent implement', args: 'user auth' });
    });

    it("parses '/agent refactor the login module'", () => {
        const result = parseSlashCommand('/agent refactor the login module');
        expect(result).toEqual({ commandName: '/agent refactor', args: 'the login module' });
    });

    it("parses '/agent explain this function'", () => {
        const result = parseSlashCommand('/agent explain this function');
        expect(result).toEqual({ commandName: '/agent explain', args: 'this function' });
    });

    it("parses '/agent build' with no args", () => {
        const result = parseSlashCommand('/agent build');
        expect(result).toEqual({ commandName: '/agent build', args: '' });
    });

    it("returns null for 'hello world' (no slash)", () => {
        expect(parseSlashCommand('hello world')).toBeNull();
    });

    it("returns null for '/unknown command'", () => {
        expect(parseSlashCommand('/unknown command')).toBeNull();
    });

    it("returns null for '/agentbuild' (no space after agent)", () => {
        expect(parseSlashCommand('/agentbuild')).toBeNull();
    });
});

describe('handleSlashCommand', () => {
    it("returns matched:true and expanded prompt for '/agent build a REST API'", () => {
        const result = handleSlashCommand('/agent build a REST API');
        expect(result.matched).toBe(true);
        expect(result.prompt).toBe('Build the project: a REST API');
    });

    it("returns matched:true for '/agent implement' with empty args", () => {
        const result = handleSlashCommand('/agent implement');
        expect(result.matched).toBe(true);
        expect(result.prompt).toBe('Implement the following feature: ');
    });

    it('returns matched:false and original input for regular text', () => {
        const result = handleSlashCommand('just some regular text');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('just some regular text');
    });

    it('returns matched:false for unrecognized slash commands', () => {
        const result = handleSlashCommand('/unknown do something');
        expect(result.matched).toBe(false);
        expect(result.prompt).toBe('/unknown do something');
    });
});

describe('SLASH_COMMANDS', () => {
    it('contains exactly 4 commands', () => {
        expect(SLASH_COMMANDS).toHaveLength(4);
    });

    it('all commands have name, command, description, promptTemplate fields', () => {
        for (const cmd of SLASH_COMMANDS) {
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
        for (const cmd of SLASH_COMMANDS) {
            expect(cmd.promptTemplate).toContain('{args}');
        }
    });
});

describe('registerCommands', () => {
    const mockSendMessage = jest.fn();
    const mockChatPanel = { sendMessage: mockSendMessage } as any;

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('registers a command for each slash command', () => {
        registerCommands(mockChatPanel);
        expect(vscode.commands.registerCommand).toHaveBeenCalledTimes(SLASH_COMMANDS.length);
        for (const cmd of SLASH_COMMANDS) {
            expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                cmd.command,
                expect.any(Function)
            );
        }
    });

    it('returns array of disposables', () => {
        const disposables = registerCommands(mockChatPanel);
        expect(Array.isArray(disposables)).toBe(true);
        expect(disposables).toHaveLength(SLASH_COMMANDS.length);
        for (const d of disposables) {
            expect(d).toHaveProperty('dispose');
        }
    });
});

describe('SlashCommandCompletionProvider', () => {
    const provider = new SlashCommandCompletionProvider();

    function makeDocAndPos(lineText: string, cursorChar?: number) {
        const pos = { line: 0, character: cursorChar ?? lineText.length } as vscode.Position;
        const doc = {
            lineAt: jest.fn().mockReturnValue({ text: lineText }),
        } as unknown as vscode.TextDocument;
        return { doc, pos };
    }

    const token = {} as vscode.CancellationToken;
    const ctx = {} as vscode.CompletionContext;

    it("returns completion items when line contains '/'", () => {
        const { doc, pos } = makeDocAndPos('/ag');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        expect(items.length).toBe(SLASH_COMMANDS.length);
    });

    it("returns empty array when line doesn't contain '/'", () => {
        const { doc, pos } = makeDocAndPos('hello world');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        expect(items).toHaveLength(0);
    });

    it('each completion item has correct label and detail', () => {
        const { doc, pos } = makeDocAndPos('/');
        const items = provider.provideCompletionItems(doc, pos, token, ctx);
        for (let i = 0; i < SLASH_COMMANDS.length; i++) {
            expect(items[i].label).toBe(SLASH_COMMANDS[i].name);
            expect(items[i].detail).toBe(SLASH_COMMANDS[i].description);
        }
    });
});

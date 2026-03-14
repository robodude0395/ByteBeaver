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
exports.SlashCommandCompletionProvider = exports.SLASH_COMMANDS = void 0;
exports.parseSlashCommand = parseSlashCommand;
exports.handleSlashCommand = handleSlashCommand;
exports.registerCommands = registerCommands;
const vscode = __importStar(require("vscode"));
/**
 * All recognized slash commands.
 */
exports.SLASH_COMMANDS = [
    {
        name: '/agent build',
        command: 'local-agent.build',
        description: 'Build or scaffold a project from scratch',
        promptTemplate: 'Build the project: {args}',
    },
    {
        name: '/agent implement',
        command: 'local-agent.implement',
        description: 'Implement a specific feature',
        promptTemplate: 'Implement the following feature: {args}',
    },
    {
        name: '/agent refactor',
        command: 'local-agent.refactor',
        description: 'Refactor existing code',
        promptTemplate: 'Refactor the following code: {args}',
    },
    {
        name: '/agent explain',
        command: 'local-agent.explain',
        description: 'Explain code in the workspace',
        promptTemplate: 'Explain the following code: {args}',
    },
];
/**
 * Parse a slash command from raw input text.
 *
 * @returns The command name and remaining arguments, or null if the input
 *          doesn't start with a recognized `/agent` prefix.
 */
function parseSlashCommand(input) {
    const trimmed = input.trim();
    if (!trimmed.startsWith('/agent')) {
        return null;
    }
    for (const cmd of exports.SLASH_COMMANDS) {
        if (trimmed === cmd.name ||
            trimmed.startsWith(cmd.name + ' ')) {
            const args = trimmed.slice(cmd.name.length).trim();
            return { commandName: cmd.name, args };
        }
    }
    // Starts with /agent but doesn't match any known command
    return null;
}
/**
 * Attempt to match the input against a known slash command and expand it
 * into a full prompt using the command's template.
 *
 * If the input doesn't match any command the original text is returned
 * unchanged with `matched: false`.
 */
function handleSlashCommand(input) {
    const parsed = parseSlashCommand(input);
    if (!parsed) {
        return { prompt: input, matched: false };
    }
    const cmd = exports.SLASH_COMMANDS.find((c) => c.name === parsed.commandName);
    if (!cmd) {
        return { prompt: input, matched: false };
    }
    const prompt = cmd.promptTemplate.replace('{args}', parsed.args);
    return { prompt, matched: true };
}
/**
 * Register VS Code commands for each slash command.
 *
 * Each command shows an input box asking for arguments, then sends the
 * expanded prompt through the chat panel.
 */
function registerCommands(chatPanel) {
    return exports.SLASH_COMMANDS.map((cmd) => vscode.commands.registerCommand(cmd.command, async () => {
        const args = await vscode.window.showInputBox({
            prompt: cmd.description,
            placeHolder: `Enter arguments for ${cmd.name}`,
        });
        if (args === undefined) {
            // User cancelled the input box
            return;
        }
        const prompt = cmd.promptTemplate.replace('{args}', args);
        await chatPanel.sendMessage(prompt);
    }));
}
/**
 * Completion provider that suggests slash commands when the user types '/'.
 */
class SlashCommandCompletionProvider {
    provideCompletionItems(document, position, _token, _context) {
        const lineText = document.lineAt(position).text;
        const textBeforeCursor = lineText.substring(0, position.character);
        if (!textBeforeCursor.includes('/')) {
            return [];
        }
        return exports.SLASH_COMMANDS.map((cmd) => {
            const item = new vscode.CompletionItem(cmd.name, vscode.CompletionItemKind.Snippet);
            item.detail = cmd.description;
            item.insertText = cmd.name;
            item.documentation = new vscode.MarkdownString(`**${cmd.name}**\n\nTemplate: \`${cmd.promptTemplate}\``);
            return item;
        });
    }
}
exports.SlashCommandCompletionProvider = SlashCommandCompletionProvider;
//# sourceMappingURL=commands.js.map
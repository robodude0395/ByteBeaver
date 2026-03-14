import * as vscode from 'vscode';
import { ChatPanel } from './chatPanel';

/**
 * Represents a slash command that maps to a VS Code command
 * and converts user input into a full prompt for the agent.
 */
export interface SlashCommand {
    /** Display name, e.g. '/agent build' */
    name: string;
    /** VS Code command ID, e.g. 'local-agent.build' */
    command: string;
    /** Human-readable description */
    description: string;
    /** Template with {args} placeholder for the user's arguments */
    promptTemplate: string;
}

/**
 * All recognized slash commands.
 */
export const SLASH_COMMANDS: SlashCommand[] = [
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
export function parseSlashCommand(
    input: string
): { commandName: string; args: string } | null {
    const trimmed = input.trim();
    if (!trimmed.startsWith('/agent')) {
        return null;
    }

    for (const cmd of SLASH_COMMANDS) {
        if (
            trimmed === cmd.name ||
            trimmed.startsWith(cmd.name + ' ')
        ) {
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
export function handleSlashCommand(
    input: string
): { prompt: string; matched: boolean } {
    const parsed = parseSlashCommand(input);
    if (!parsed) {
        return { prompt: input, matched: false };
    }

    const cmd = SLASH_COMMANDS.find((c) => c.name === parsed.commandName);
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
export function registerCommands(chatPanel: ChatPanel): vscode.Disposable[] {
    return SLASH_COMMANDS.map((cmd) =>
        vscode.commands.registerCommand(cmd.command, async () => {
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
        })
    );
}

/**
 * Completion provider that suggests slash commands when the user types '/'.
 */
export class SlashCommandCompletionProvider
    implements vscode.CompletionItemProvider
{
    provideCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken,
        _context: vscode.CompletionContext
    ): vscode.CompletionItem[] {
        const lineText = document.lineAt(position).text;
        const textBeforeCursor = lineText.substring(0, position.character);

        if (!textBeforeCursor.includes('/')) {
            return [];
        }

        return SLASH_COMMANDS.map((cmd) => {
            const item = new vscode.CompletionItem(
                cmd.name,
                vscode.CompletionItemKind.Snippet
            );
            item.detail = cmd.description;
            item.insertText = cmd.name;
            item.documentation = new vscode.MarkdownString(
                `**${cmd.name}**\n\nTemplate: \`${cmd.promptTemplate}\``
            );
            return item;
        });
    }
}

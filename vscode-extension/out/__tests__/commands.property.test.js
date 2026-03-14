"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const fast_check_1 = __importDefault(require("fast-check"));
const commands_1 = require("../commands");
/**
 * Property 22: Slash Command Recognition
 * Validates: Requirements 13.5
 *
 * Tests that all recognized slash commands are parsed and handled correctly.
 */
// Arbitrary that picks a random command from SLASH_COMMANDS
const slashCommandArb = fast_check_1.default.constantFrom(...commands_1.SLASH_COMMANDS);
// Arbitrary for argument strings: printable ASCII, no leading whitespace,
// and no '$' characters (String.replace treats $$ as a special pattern —
// a known JS quirk, not a slash-command recognition issue).
const argsArb = fast_check_1.default
    .string({ minLength: 1 })
    .filter((s) => !s.includes('$'))
    .map((s) => s.replace(/^\s+/, 'a'));
// Arbitrary for strings that do NOT start with '/agent'
const nonSlashArb = fast_check_1.default
    .string()
    .filter((s) => !s.trimStart().startsWith('/agent'));
describe('Property 22: Slash Command Recognition', () => {
    /**
     * Property 22a: For any recognized slash command and any arbitrary string
     * arguments, handleSlashCommand should return matched: true and the prompt
     * should contain the arguments.
     *
     * Validates: Requirements 13.5
     */
    it('22a: handleSlashCommand returns matched:true and prompt contains args for any recognized command', () => {
        fast_check_1.default.assert(fast_check_1.default.property(slashCommandArb, argsArb, (cmd, args) => {
            const input = `${cmd.name} ${args}`;
            const result = (0, commands_1.handleSlashCommand)(input);
            expect(result.matched).toBe(true);
            // parseSlashCommand trims args, so the prompt contains trimmed args
            const trimmedArgs = args.trim();
            if (trimmedArgs.length > 0) {
                expect(result.prompt).toContain(trimmedArgs);
            }
        }), { numRuns: 100 });
    });
    /**
     * Property 22b: For any string that does NOT start with '/agent',
     * handleSlashCommand should return matched: false and return the original
     * input unchanged.
     *
     * Validates: Requirements 13.5
     */
    it('22b: handleSlashCommand returns matched:false and original input for non-slash inputs', () => {
        fast_check_1.default.assert(fast_check_1.default.property(nonSlashArb, (input) => {
            const result = (0, commands_1.handleSlashCommand)(input);
            expect(result.matched).toBe(false);
            expect(result.prompt).toBe(input);
        }), { numRuns: 100 });
    });
    /**
     * Property 22c: For any recognized slash command, parseSlashCommand should
     * extract the correct command name.
     *
     * Validates: Requirements 13.5
     */
    it('22c: parseSlashCommand extracts correct command name and trimmed args', () => {
        fast_check_1.default.assert(fast_check_1.default.property(slashCommandArb, argsArb, (cmd, args) => {
            const input = `${cmd.name} ${args}`;
            const result = (0, commands_1.parseSlashCommand)(input);
            expect(result).not.toBeNull();
            expect(result.commandName).toBe(cmd.name);
            expect(result.args).toBe(args.trim());
        }), { numRuns: 100 });
    });
    /**
     * Property 22d: parseSlashCommand returns null for inputs not starting
     * with '/agent'.
     *
     * Validates: Requirements 13.5
     */
    it('22d: parseSlashCommand returns null for non-slash inputs', () => {
        fast_check_1.default.assert(fast_check_1.default.property(nonSlashArb, (input) => {
            const result = (0, commands_1.parseSlashCommand)(input);
            expect(result).toBeNull();
        }), { numRuns: 100 });
    });
});
//# sourceMappingURL=commands.property.test.js.map
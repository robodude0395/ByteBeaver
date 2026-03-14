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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const agentClient_1 = require("./agentClient");
const chatPanel_1 = require("./chatPanel");
const diffProvider_1 = require("./diffProvider");
const statusBar_1 = require("./statusBar");
const commands_1 = require("./commands");
function activate(context) {
    // Read configuration
    const config = vscode.workspace.getConfiguration('agent');
    const serverUrl = config.get('serverUrl', 'http://localhost:8000');
    // Initialize agent client
    const agentClient = new agentClient_1.AgentClient(serverUrl);
    // Create and register chat panel
    const chatPanel = new chatPanel_1.ChatPanel(context.extensionUri, agentClient);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider(chatPanel_1.ChatPanel.viewType, chatPanel));
    // Create diff provider
    const diffProvider = new diffProvider_1.DiffProvider(agentClient, context.extensionUri);
    context.subscriptions.push(diffProvider);
    // Create status bar
    const statusBar = new statusBar_1.AgentStatusBar();
    context.subscriptions.push(statusBar);
    // Register openChat command
    context.subscriptions.push(vscode.commands.registerCommand('local-agent.openChat', () => {
        chatPanel.show();
    }));
    // Register accept/reject changes commands
    context.subscriptions.push(vscode.commands.registerCommand('local-agent.acceptChanges', () => {
        void diffProvider.acceptChanges();
    }), vscode.commands.registerCommand('local-agent.rejectChanges', () => {
        void diffProvider.rejectChanges();
    }));
    // Register slash commands (build, implement, refactor, explain)
    const commandDisposables = (0, commands_1.registerCommands)(chatPanel);
    context.subscriptions.push(...commandDisposables);
    // Register cancelSession command
    context.subscriptions.push(vscode.commands.registerCommand('local-agent.cancelSession', async () => {
        const sessionId = await vscode.window.showInputBox({
            prompt: 'Enter session ID to cancel',
            placeHolder: 'session-id',
        });
        if (sessionId) {
            try {
                await agentClient.cancelSession(sessionId);
                void vscode.window.showInformationMessage('Session cancelled successfully.');
            }
            catch (error) {
                const message = error instanceof Error
                    ? error.message
                    : 'Unknown error';
                void vscode.window.showErrorMessage(`Failed to cancel session: ${message}`);
            }
        }
    }));
}
function deactivate() {
    // Cleanup handled by disposables in context.subscriptions
}
//# sourceMappingURL=extension.js.map
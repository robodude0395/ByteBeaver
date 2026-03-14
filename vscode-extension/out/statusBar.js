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
exports.AgentStatusBar = void 0;
const vscode = __importStar(require("vscode"));
/**
 * Status bar item that displays the current agent state, progress,
 * and opens the chat panel on click.
 */
class AgentStatusBar {
    constructor() {
        this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.statusBarItem.command = 'local-agent.openChat';
        this.currentState = 'idle';
        this.applyState();
        this.statusBarItem.show();
    }
    /**
     * Update the displayed agent state.
     */
    setState(state) {
        this.currentState = state;
        this.applyState();
    }
    /**
     * Show a progress percentage in the status bar.
     * Optionally set a tooltip describing the current task.
     */
    setProgress(progress, taskDescription) {
        const pct = Math.round(progress);
        this.statusBarItem.text = `$(loading~spin) Agent: ${pct}%`;
        this.statusBarItem.tooltip = taskDescription ?? `Agent progress: ${pct}%`;
    }
    /**
     * Return the current agent state.
     */
    getState() {
        return this.currentState;
    }
    /**
     * Dispose the underlying status bar item.
     */
    dispose() {
        this.statusBarItem.dispose();
    }
    applyState() {
        switch (this.currentState) {
            case 'idle':
                this.statusBarItem.text = '$(robot) Agent: Idle';
                this.statusBarItem.tooltip = 'Agent is idle';
                break;
            case 'planning':
                this.statusBarItem.text = '$(loading~spin) Agent: Planning...';
                this.statusBarItem.tooltip = 'Agent is generating a plan';
                break;
            case 'executing':
                this.statusBarItem.text = '$(loading~spin) Agent: Executing...';
                this.statusBarItem.tooltip = 'Agent is executing tasks';
                break;
            case 'error':
                this.statusBarItem.text = '$(error) Agent: Error';
                this.statusBarItem.tooltip = 'Agent encountered an error';
                break;
        }
    }
}
exports.AgentStatusBar = AgentStatusBar;
//# sourceMappingURL=statusBar.js.map
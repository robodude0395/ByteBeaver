import * as vscode from 'vscode';

/**
 * Possible states for the agent status bar indicator.
 */
export type AgentState = 'idle' | 'planning' | 'executing' | 'error';

/**
 * Status bar item that displays the current agent state, progress,
 * and opens the chat panel on click.
 */
export class AgentStatusBar {
    private statusBarItem: vscode.StatusBarItem;
    private currentState: AgentState;

    constructor() {
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Left,
            100
        );
        this.statusBarItem.command = 'local-agent.openChat';
        this.currentState = 'idle';
        this.applyState();
        this.statusBarItem.show();
    }

    /**
     * Update the displayed agent state.
     */
    public setState(state: AgentState): void {
        this.currentState = state;
        this.applyState();
    }

    /**
     * Show a progress percentage in the status bar.
     * Optionally set a tooltip describing the current task.
     */
    public setProgress(progress: number, taskDescription?: string): void {
        const pct = Math.round(progress);
        this.statusBarItem.text = `$(loading~spin) Agent: ${pct}%`;
        this.statusBarItem.tooltip = taskDescription ?? `Agent progress: ${pct}%`;
    }

    /**
     * Return the current agent state.
     */
    public getState(): AgentState {
        return this.currentState;
    }

    /**
     * Dispose the underlying status bar item.
     */
    public dispose(): void {
        this.statusBarItem.dispose();
    }

    private applyState(): void {
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

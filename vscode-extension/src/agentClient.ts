import axios, { AxiosInstance, AxiosError } from 'axios';

// Request interfaces

export interface PromptRequest {
    prompt: string;
    workspace_path: string;
    session_id?: string;
}

export interface ApplyChangesRequest {
    session_id: string;
    change_ids: string[];
}

export interface CancelRequest {
    session_id: string;
}

export interface NotifyAppliedRequest {
    session_id: string;
    change_ids: string[];
}

// Response interfaces

export interface TaskInfo {
    task_id: string;
    description: string;
    dependencies: string[];
    estimated_complexity: string;
}

export interface PlanInfo {
    tasks: TaskInfo[];
}

export interface PromptResponse {
    session_id: string;
    plan?: PlanInfo;
    status: string;
}

export interface FileChangeInfo {
    change_id: string;
    file_path: string;
    change_type: string;
    diff: string;
    new_content?: string;
}

export interface StatusResponse {
    session_id: string;
    status: string;
    current_task?: string;
    completed_tasks: string[];
    pending_tasks: string[];
    failed_tasks: string[];
    pending_changes: FileChangeInfo[];
    progress: number;
}

export interface ApplyChangesResponse {
    applied: string[];
    failed: string[];
    errors: Record<string, string>;
}

export interface CancelResponse {
    status: string;
}

// Agent client class

export class AgentClient {
    private client: AxiosInstance;

    constructor(baseUrl: string) {
        this.client = axios.create({
            baseURL: baseUrl,
            timeout: 30000,
            headers: {
                'Content-Type': 'application/json',
            },
        });
    }

    async sendPrompt(
        prompt: string,
        workspacePath: string,
        sessionId?: string
    ): Promise<PromptResponse> {
        try {
            const payload: PromptRequest = {
                prompt,
                workspace_path: workspacePath,
            };
            if (sessionId) {
                payload.session_id = sessionId;
            }
            const response = await this.client.post<PromptResponse>(
                '/agent/prompt',
                payload
            );
            return response.data;
        } catch (error) {
            throw this.handleError(error, 'Failed to send prompt');
        }
    }

    async getStatus(sessionId: string): Promise<StatusResponse> {
        try {
            const response = await this.client.get<StatusResponse>(
                `/agent/status/${sessionId}`
            );
            return response.data;
        } catch (error) {
            throw this.handleError(error, 'Failed to get session status');
        }
    }

    async applyChanges(
        sessionId: string,
        changeIds: string[]
    ): Promise<ApplyChangesResponse> {
        try {
            const payload: ApplyChangesRequest = {
                session_id: sessionId,
                change_ids: changeIds,
            };
            const response = await this.client.post<ApplyChangesResponse>(
                '/agent/apply_changes',
                payload
            );
            return response.data;
        } catch (error) {
            throw this.handleError(error, 'Failed to apply changes');
        }
    }

    async cancelSession(sessionId: string): Promise<CancelResponse> {
        try {
            const payload: CancelRequest = {
                session_id: sessionId,
            };
            const response = await this.client.post<CancelResponse>(
                '/agent/cancel',
                payload
            );
            return response.data;
        } catch (error) {
            throw this.handleError(error, 'Failed to cancel session');
        }
    }

    /**
     * Notify the server that changes were applied locally.
     * This is best-effort — failures are logged, not thrown.
     */
    async notifyChangesApplied(
        sessionId: string,
        changeIds: string[]
    ): Promise<void> {
        try {
            const payload: NotifyAppliedRequest = {
                session_id: sessionId,
                change_ids: changeIds,
            };
            await this.client.post('/agent/notify_applied', payload);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            console.error(`Failed to notify server of applied changes: ${message}`);
        }
    }

    async healthCheck(): Promise<boolean> {
        try {
            const response = await this.client.get('/health');
            return response.status === 200;
        } catch (_error) {
            return false;
        }
    }

    private handleError(error: unknown, context: string): Error {
        if (error instanceof AxiosError) {
            if (error.code === 'ECONNREFUSED') {
                return new Error(
                    `${context}: Agent server is not reachable. Is it running?`
                );
            }
            if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
                return new Error(
                    `${context}: Request timed out. The server may be overloaded.`
                );
            }
            if (error.response) {
                const status = error.response.status;
                const data = error.response.data;
                const detail =
                    typeof data === 'object' && data !== null && 'detail' in data
                        ? (data as { detail: string }).detail
                        : JSON.stringify(data);
                return new Error(
                    `${context}: Server returned ${status} - ${detail}`
                );
            }
            return new Error(`${context}: ${error.message}`);
        }
        if (error instanceof Error) {
            return new Error(`${context}: ${error.message}`);
        }
        return new Error(`${context}: An unknown error occurred`);
    }
}

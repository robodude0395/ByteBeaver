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
exports.AgentClient = void 0;
const axios_1 = __importStar(require("axios"));
// Agent client class
class AgentClient {
    constructor(baseUrl) {
        this.client = axios_1.default.create({
            baseURL: baseUrl,
            timeout: 30000,
            headers: {
                'Content-Type': 'application/json',
            },
        });
    }
    async sendPrompt(prompt, workspacePath, sessionId) {
        try {
            const payload = {
                prompt,
                workspace_path: workspacePath,
            };
            if (sessionId) {
                payload.session_id = sessionId;
            }
            const response = await this.client.post('/agent/prompt', payload);
            return response.data;
        }
        catch (error) {
            throw this.handleError(error, 'Failed to send prompt');
        }
    }
    async getStatus(sessionId) {
        try {
            const response = await this.client.get(`/agent/status/${sessionId}`);
            return response.data;
        }
        catch (error) {
            throw this.handleError(error, 'Failed to get session status');
        }
    }
    async applyChanges(sessionId, changeIds) {
        try {
            const payload = {
                session_id: sessionId,
                change_ids: changeIds,
            };
            const response = await this.client.post('/agent/apply_changes', payload);
            return response.data;
        }
        catch (error) {
            throw this.handleError(error, 'Failed to apply changes');
        }
    }
    async cancelSession(sessionId) {
        try {
            const payload = {
                session_id: sessionId,
            };
            const response = await this.client.post('/agent/cancel', payload);
            return response.data;
        }
        catch (error) {
            throw this.handleError(error, 'Failed to cancel session');
        }
    }
    /**
     * Notify the server that changes were applied locally.
     * This is best-effort — failures are logged, not thrown.
     */
    async notifyChangesApplied(sessionId, changeIds) {
        try {
            const payload = {
                session_id: sessionId,
                change_ids: changeIds,
            };
            await this.client.post('/agent/notify_applied', payload);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            console.error(`Failed to notify server of applied changes: ${message}`);
        }
    }
    async healthCheck() {
        try {
            const response = await this.client.get('/health');
            return response.status === 200;
        }
        catch (_error) {
            return false;
        }
    }
    handleError(error, context) {
        if (error instanceof axios_1.AxiosError) {
            if (error.code === 'ECONNREFUSED') {
                return new Error(`${context}: Agent server is not reachable. Is it running?`);
            }
            if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
                return new Error(`${context}: Request timed out. The server may be overloaded.`);
            }
            if (error.response) {
                const status = error.response.status;
                const data = error.response.data;
                const detail = typeof data === 'object' && data !== null && 'detail' in data
                    ? data.detail
                    : JSON.stringify(data);
                return new Error(`${context}: Server returned ${status} - ${detail}`);
            }
            return new Error(`${context}: ${error.message}`);
        }
        if (error instanceof Error) {
            return new Error(`${context}: ${error.message}`);
        }
        return new Error(`${context}: An unknown error occurred`);
    }
}
exports.AgentClient = AgentClient;
//# sourceMappingURL=agentClient.js.map
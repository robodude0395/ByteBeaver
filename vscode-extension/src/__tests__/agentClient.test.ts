import axios from 'axios';
import { AgentClient } from '../agentClient';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('AgentClient', () => {
  let client: AgentClient;
  let mockAxiosInstance: {
    post: jest.Mock;
    get: jest.Mock;
  };

  beforeEach(() => {
    mockAxiosInstance = {
      post: jest.fn(),
      get: jest.fn(),
    };
    mockedAxios.create.mockReturnValue(mockAxiosInstance as any);
    client = new AgentClient('http://localhost:8000');
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  describe('sendPrompt', () => {
    it('returns PromptResponse on success', async () => {
      const responseData = {
        session_id: 'sess-1',
        plan: { tasks: [{ task_id: 't1', description: 'do stuff', dependencies: [], estimated_complexity: 'low' }] },
        status: 'executing',
      };
      mockAxiosInstance.post.mockResolvedValue({ data: responseData });

      const result = await client.sendPrompt('build a thing', '/workspace');

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/agent/prompt', {
        prompt: 'build a thing',
        workspace_path: '/workspace',
      });
      expect(result).toEqual(responseData);
    });

    it('includes session_id when provided', async () => {
      mockAxiosInstance.post.mockResolvedValue({ data: { session_id: 's1', status: 'executing' } });

      await client.sendPrompt('test', '/ws', 'existing-session');

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/agent/prompt', {
        prompt: 'test',
        workspace_path: '/ws',
        session_id: 'existing-session',
      });
    });

    it('omits session_id when not provided', async () => {
      mockAxiosInstance.post.mockResolvedValue({ data: { session_id: 's1', status: 'executing' } });

      await client.sendPrompt('test', '/ws');

      const payload = mockAxiosInstance.post.mock.calls[0][1];
      expect(payload).not.toHaveProperty('session_id');
    });
  });

  describe('getStatus', () => {
    it('returns StatusResponse on success', async () => {
      const responseData = {
        session_id: 'sess-1',
        status: 'executing',
        current_task: 'task-1',
        completed_tasks: ['task-0'],
        pending_tasks: ['task-2'],
        failed_tasks: [],
        pending_changes: [],
        progress: 0.5,
      };
      mockAxiosInstance.get.mockResolvedValue({ data: responseData });

      const result = await client.getStatus('sess-1');

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/agent/status/sess-1');
      expect(result).toEqual(responseData);
    });

    it('throws meaningful error on 404', async () => {
      const axiosError = new (axios as any).AxiosError('Not Found');
      axiosError.response = { status: 404, data: { detail: 'Session not found' } };
      mockAxiosInstance.get.mockRejectedValue(axiosError);

      await expect(client.getStatus('bad-id')).rejects.toThrow(
        'Failed to get session status: Server returned 404 - Session not found'
      );
    });
  });

  describe('applyChanges', () => {
    it('returns ApplyChangesResponse on success', async () => {
      const responseData = {
        applied: ['c1', 'c2'],
        failed: [],
        errors: {},
      };
      mockAxiosInstance.post.mockResolvedValue({ data: responseData });

      const result = await client.applyChanges('sess-1', ['c1', 'c2']);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/agent/apply_changes', {
        session_id: 'sess-1',
        change_ids: ['c1', 'c2'],
      });
      expect(result).toEqual(responseData);
    });
  });

  describe('cancelSession', () => {
    it('returns CancelResponse on success', async () => {
      mockAxiosInstance.post.mockResolvedValue({ data: { status: 'cancelled' } });

      const result = await client.cancelSession('sess-1');

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/agent/cancel', {
        session_id: 'sess-1',
      });
      expect(result).toEqual({ status: 'cancelled' });
    });
  });

  describe('healthCheck', () => {
    it('returns true when server is healthy', async () => {
      mockAxiosInstance.get.mockResolvedValue({ status: 200 });

      const result = await client.healthCheck();

      expect(result).toBe(true);
      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/health');
    });

    it('returns false when server is unreachable', async () => {
      mockAxiosInstance.get.mockRejectedValue(new Error('ECONNREFUSED'));

      const result = await client.healthCheck();

      expect(result).toBe(false);
    });
  });

  describe('notifyChangesApplied', () => {
    it('posts to /agent/notify_applied with correct payload', async () => {
      mockAxiosInstance.post.mockResolvedValue({ data: {} });

      await client.notifyChangesApplied('sess-1', ['c1', 'c2']);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/agent/notify_applied', {
        session_id: 'sess-1',
        change_ids: ['c1', 'c2'],
      });
    });

    it('does not throw when the server returns a network error', async () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      mockAxiosInstance.post.mockRejectedValue(new Error('Network Error'));

      await expect(client.notifyChangesApplied('sess-1', ['c1'])).resolves.toBeUndefined();

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Failed to notify server of applied changes')
      );
      consoleSpy.mockRestore();
    });

    it('does not throw when the server returns 500', async () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      const axiosError = new (axios as any).AxiosError('Internal Server Error');
      axiosError.response = { status: 500, data: { detail: 'Server crashed' } };
      mockAxiosInstance.post.mockRejectedValue(axiosError);

      await expect(client.notifyChangesApplied('sess-1', ['c1'])).resolves.toBeUndefined();

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Failed to notify server of applied changes')
      );
      consoleSpy.mockRestore();
    });
  });

  describe('error handling', () => {
    it('gives clear error on connection refused', async () => {
      const axiosError = new (axios as any).AxiosError('connect ECONNREFUSED');
      axiosError.code = 'ECONNREFUSED';
      mockAxiosInstance.post.mockRejectedValue(axiosError);

      await expect(client.sendPrompt('test', '/ws')).rejects.toThrow(
        'Failed to send prompt: Agent server is not reachable. Is it running?'
      );
    });

    it('gives clear error on timeout', async () => {
      const axiosError = new (axios as any).AxiosError('timeout');
      axiosError.code = 'ECONNABORTED';
      mockAxiosInstance.post.mockRejectedValue(axiosError);

      await expect(client.sendPrompt('test', '/ws')).rejects.toThrow(
        'Failed to send prompt: Request timed out. The server may be overloaded.'
      );
    });

    it('includes detail from 500 server error', async () => {
      const axiosError = new (axios as any).AxiosError('Internal Server Error');
      axiosError.response = { status: 500, data: { detail: 'LLM server crashed' } };
      mockAxiosInstance.post.mockRejectedValue(axiosError);

      await expect(client.sendPrompt('test', '/ws')).rejects.toThrow(
        'Failed to send prompt: Server returned 500 - LLM server crashed'
      );
    });
  });
});

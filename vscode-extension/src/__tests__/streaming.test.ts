import axios from 'axios';
import { AgentClient, StreamEvent } from '../agentClient';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

/**
 * Helper: build a ReadableStream from SSE text chunks.
 */
function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    let index = 0;
    return new ReadableStream<Uint8Array>({
        pull(controller) {
            if (index < chunks.length) {
                controller.enqueue(encoder.encode(chunks[index]));
                index++;
            } else {
                controller.close();
            }
        },
    });
}

describe('AgentClient.sendPromptStreaming', () => {
    let client: AgentClient;
    let mockAxiosInstance: { post: jest.Mock; get: jest.Mock };

    beforeEach(() => {
        mockAxiosInstance = { post: jest.fn(), get: jest.fn() };
        mockedAxios.create.mockReturnValue(mockAxiosInstance as any);
        client = new AgentClient('http://localhost:8000');
    });

    afterEach(() => jest.resetAllMocks());

    it('parses session, token, and done events', async () => {
        const sseText = [
            'event: session\ndata: {"session_id":"s1"}\n\n',
            'event: token\ndata: "hello"\n\n',
            'event: token\ndata: " world"\n\n',
            'event: done\ndata: {"status":"completed","session_id":"s1"}\n\n',
        ];
        mockAxiosInstance.post.mockResolvedValue({
            data: sseStream(sseText),
        });

        const events: StreamEvent[] = [];
        await client.sendPromptStreaming('test', '/ws', (e) => events.push(e));

        expect(events).toHaveLength(4);
        expect(events[0]).toEqual({ event: 'session', data: { session_id: 's1' } });
        expect(events[1]).toEqual({ event: 'token', data: 'hello' });
        expect(events[2]).toEqual({ event: 'token', data: ' world' });
        expect(events[3]).toEqual({
            event: 'done',
            data: { status: 'completed', session_id: 's1' },
        });
    });

    it('handles plan events', async () => {
        const sseText = [
            'event: session\ndata: {"session_id":"s1"}\n\n' +
            'event: plan\ndata: {"tasks":[{"task_id":"t1","description":"do it","dependencies":[],"estimated_complexity":"low"}]}\n\n' +
            'event: done\ndata: {"status":"completed","session_id":"s1"}\n\n',
        ];
        mockAxiosInstance.post.mockResolvedValue({
            data: sseStream(sseText),
        });

        const events: StreamEvent[] = [];
        await client.sendPromptStreaming('test', '/ws', (e) => events.push(e));

        const planEvents = events.filter((e) => e.event === 'plan');
        expect(planEvents).toHaveLength(1);
        expect(planEvents[0].data.tasks[0].task_id).toBe('t1');
    });

    it('passes session_id when provided', async () => {
        mockAxiosInstance.post.mockResolvedValue({
            data: sseStream(['event: done\ndata: {"status":"completed","session_id":"s1"}\n\n']),
        });

        await client.sendPromptStreaming('test', '/ws', () => {}, 'existing-session');

        const payload = mockAxiosInstance.post.mock.calls[0][1];
        expect(payload.session_id).toBe('existing-session');
    });

    it('calls the correct endpoint with stream options', async () => {
        mockAxiosInstance.post.mockResolvedValue({
            data: sseStream(['event: done\ndata: {"status":"done","session_id":"s1"}\n\n']),
        });

        await client.sendPromptStreaming('build it', '/workspace', () => {});

        expect(mockAxiosInstance.post).toHaveBeenCalledWith(
            '/agent/prompt/stream',
            expect.objectContaining({ prompt: 'build it', workspace_path: '/workspace' }),
            expect.objectContaining({ responseType: 'stream', timeout: 0 }),
        );
    });

    it('handles error events from server', async () => {
        const sseText = [
            'event: session\ndata: {"session_id":"s1"}\n\n',
            'event: error\ndata: {"error":"LLM crashed"}\n\n',
        ];
        mockAxiosInstance.post.mockResolvedValue({
            data: sseStream(sseText),
        });

        const events: StreamEvent[] = [];
        await client.sendPromptStreaming('test', '/ws', (e) => events.push(e));

        const errorEvents = events.filter((e) => e.event === 'error');
        expect(errorEvents).toHaveLength(1);
        expect(errorEvents[0].data.error).toBe('LLM crashed');
    });
});

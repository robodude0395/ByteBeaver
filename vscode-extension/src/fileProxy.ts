/**
 * Lightweight HTTP file proxy server.
 *
 * Runs inside the VSCode extension process and exposes the local workspace
 * filesystem over HTTP so the remote agent server can read/list/search files
 * without direct access to the client machine.
 */
import * as http from 'http';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class FileProxyServer {
    private server: http.Server | null = null;
    private port = 0;

    /** Start the proxy on a random available port. Returns the chosen port. */
    async start(): Promise<number> {
        if (this.server) {
            return this.port;
        }

        return new Promise((resolve, reject) => {
            this.server = http.createServer((req, res) =>
                this.handleRequest(req, res)
            );
            // Listen on 0 = OS picks a free port
            this.server.listen(0, '0.0.0.0', () => {
                const addr = this.server!.address();
                if (addr && typeof addr === 'object') {
                    this.port = addr.port;
                    console.log(`File proxy server listening on port ${this.port}`);
                    resolve(this.port);
                } else {
                    reject(new Error('Failed to get server address'));
                }
            });
            this.server.on('error', reject);
        });
    }

    /** Stop the proxy server. */
    stop(): void {
        if (this.server) {
            this.server.close();
            this.server = null;
            this.port = 0;
        }
    }

    getPort(): number {
        return this.port;
    }

    private getWorkspaceRoot(): string | null {
        const folders = vscode.workspace.workspaceFolders;
        if (folders && folders.length > 0) {
            return folders[0].uri.fsPath;
        }
        return null;
    }

    /**
     * Resolve a relative path against the workspace root.
     * Returns null if the resolved path escapes the workspace.
     */
    private safePath(relativePath: string): string | null {
        const root = this.getWorkspaceRoot();
        if (!root) { return null; }

        // Reject parent traversal
        if (relativePath.includes('..')) { return null; }

        const resolved = path.resolve(root, relativePath);
        if (!resolved.startsWith(root + path.sep) && resolved !== root) {
            return null;
        }
        return resolved;
    }

    private async handleRequest(
        req: http.IncomingMessage,
        res: http.ServerResponse
    ): Promise<void> {
        // Parse JSON body for POST requests
        let body: Record<string, unknown> = {};
        if (req.method === 'POST') {
            try {
                body = await this.readBody(req);
            } catch {
                this.sendJson(res, 400, { error: 'Invalid JSON body' });
                return;
            }
        }

        const url = req.url ?? '/';

        try {
            if (url === '/read_file' && req.method === 'POST') {
                await this.handleReadFile(body, res);
            } else if (url === '/list_directory' && req.method === 'POST') {
                await this.handleListDirectory(body, res);
            } else if (url === '/search_files' && req.method === 'POST') {
                await this.handleSearchFiles(body, res);
            } else if (url === '/write_file' && req.method === 'POST') {
                await this.handleWriteFile(body, res);
            } else if (url === '/health' && req.method === 'GET') {
                this.sendJson(res, 200, { status: 'ok', workspace: this.getWorkspaceRoot() });
            } else {
                this.sendJson(res, 404, { error: 'Not found' });
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            this.sendJson(res, 500, { error: message });
        }
    }

    private async handleReadFile(
        body: Record<string, unknown>,
        res: http.ServerResponse
    ): Promise<void> {
        const filePath = body.path as string;
        if (!filePath) {
            this.sendJson(res, 400, { error: 'Missing "path" parameter' });
            return;
        }
        const abs = this.safePath(filePath);
        if (!abs) {
            this.sendJson(res, 403, { error: 'Path not allowed' });
            return;
        }
        if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) {
            this.sendJson(res, 404, { error: `File not found: ${filePath}` });
            return;
        }
        const content = fs.readFileSync(abs, 'utf-8');
        this.sendJson(res, 200, { content });
    }

    private async handleListDirectory(
        body: Record<string, unknown>,
        res: http.ServerResponse
    ): Promise<void> {
        const dirPath = (body.path as string) || '.';
        const abs = this.safePath(dirPath);
        if (!abs) {
            this.sendJson(res, 403, { error: 'Path not allowed' });
            return;
        }
        if (!fs.existsSync(abs) || !fs.statSync(abs).isDirectory()) {
            this.sendJson(res, 404, { error: `Directory not found: ${dirPath}` });
            return;
        }
        const entries = fs.readdirSync(abs)
            .filter(e => !e.startsWith('.'))
            .sort()
            .map(e => {
                const full = path.join(abs, e);
                return fs.statSync(full).isDirectory() ? e + '/' : e;
            });
        this.sendJson(res, 200, { entries });
    }

    private async handleSearchFiles(
        body: Record<string, unknown>,
        res: http.ServerResponse
    ): Promise<void> {
        const query = body.query as string;
        if (!query) {
            this.sendJson(res, 400, { error: 'Missing "query" parameter' });
            return;
        }
        const root = this.getWorkspaceRoot();
        if (!root) {
            this.sendJson(res, 500, { error: 'No workspace open' });
            return;
        }
        // Use vscode's findFiles for glob matching
        const pattern = new vscode.RelativePattern(root, query);
        const uris = await vscode.workspace.findFiles(pattern, '**/node_modules/**', 500);
        const files = uris.map(u => path.relative(root, u.fsPath)).sort();
        this.sendJson(res, 200, { files });
    }

    private async handleWriteFile(
        body: Record<string, unknown>,
        res: http.ServerResponse
    ): Promise<void> {
        const filePath = body.path as string;
        const contents = body.contents as string;
        if (!filePath || contents === undefined) {
            this.sendJson(res, 400, { error: 'Missing "path" or "contents"' });
            return;
        }
        const abs = this.safePath(filePath);
        if (!abs) {
            this.sendJson(res, 403, { error: 'Path not allowed' });
            return;
        }
        const dir = path.dirname(abs);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
        fs.writeFileSync(abs, contents, 'utf-8');
        this.sendJson(res, 200, { status: 'ok' });
    }

    private readBody(req: http.IncomingMessage): Promise<Record<string, unknown>> {
        return new Promise((resolve, reject) => {
            let data = '';
            req.on('data', chunk => { data += chunk; });
            req.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { reject(new Error('Invalid JSON')); }
            });
            req.on('error', reject);
        });
    }

    private sendJson(res: http.ServerResponse, status: number, data: unknown): void {
        res.writeHead(status, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(data));
    }
}

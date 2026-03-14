# Local Offline Coding Agent - VSCode Extension

A VSCode extension that connects to a self-hosted AI coding agent running entirely on your local machine. Send prompts, review proposed code changes in a diff view, and accept or reject edits — all without leaving your editor or sending code to the cloud.

## Prerequisites

Before using this extension, ensure both backend servers are running:

1. **Agent Server** — Python FastAPI server at `http://localhost:8000`
   ```bash
   ./scripts/run_agent.sh
   ```

2. **LLM Server** — llama.cpp with Qwen2.5-Coder-7B-Instruct at `http://localhost:8001`
   ```bash
   ./scripts/run_llm.sh
   ```

See the project root README for full setup instructions.

## Installation

### From VSIX

```bash
code --install-extension local-offline-coding-agent-0.0.1.vsix
```

### From Source

```bash
cd vscode-extension
npm install
npm run compile
```

Then press `F5` in VSCode to launch the Extension Development Host with the extension loaded.

## Features

- **Chat panel** in the sidebar for conversing with the agent
- **Diff preview** for reviewing proposed code changes before applying them
- **Accept / Reject buttons** to control which changes land in your workspace
- **Progress indicators** in the status bar showing planning and execution state
- **Slash commands** for common operations (see below)

<!-- Screenshot: Chat panel with a conversation and task progress -->
<!-- Screenshot: Diff view showing proposed file changes with accept/reject actions -->

## Slash Commands

Type these in the chat panel to trigger specific workflows:

| Command | Description |
|---------|-------------|
| `/agent build` | Build or scaffold a project from a description |
| `/agent implement` | Implement a specific feature in the workspace |
| `/agent refactor` | Refactor existing code (rename, extract, restructure) |
| `/agent explain` | Explain code in the current workspace |

## Configuration

Open **Settings** (`Ctrl+,`) and search for "Agent" to find these options:

| Setting | Default | Description |
|---------|---------|-------------|
| `agent.serverUrl` | `http://localhost:8000` | URL of the agent server |
| `agent.autoApplyChanges` | `false` | Automatically apply changes without diff review |

## Development

```bash
npm run compile    # Build the extension
npm run watch      # Watch mode for development
npm test           # Run tests
npm run package    # Package as .vsix for distribution
```

# Product Overview

A self-hosted AI coding agent that runs on a remote desktop machine with local GPU
acceleration. It provides an alternative to cloud-based coding assistants (Copilot,
ChatGPT, Kiro) by running entirely offline using open-source LLMs. The user retains
full control over their code, data, and infrastructure.

Target hardware: NVIDIA RTX 3080 (10GB VRAM), 32GB RAM, 6+ core CPU.

## Architecture

The system is a three-layer pipeline:

1. Planner — breaks a user prompt into a structured task list (JSON) via LLM
2. Executor — processes each task by calling the LLM, parsing directives
   (WRITE_FILE, PATCH_FILE, TOOL_CALL), and running them through the tool system
3. Tool System — unified registry of filesystem, terminal, and web tools

Supporting subsystems:
- Context Engine — indexes the workspace into a vector DB (Qdrant) using
  sentence-transformers embeddings, then provides semantic search so the LLM
  receives relevant code snippets in its prompt
- SSE Streaming — tokens stream to the client in real time via Server-Sent Events
- Review-before-apply — proposed file changes are returned as diffs; the client
  (VSCode extension) presents them for approval before writing to disk

## VSCode Extension

A sidebar webview extension that connects to the agent server over HTTP. Supports
chat input, streaming responses, diff preview, and one-click apply/reject of
proposed changes. Configurable server URL for remote-desktop setups.

## Current State (MVP)

All core infrastructure is functional: planning, execution, tool invocation,
context-aware prompts, streaming, and the VSCode extension. The agent can receive
a coding request, plan tasks, generate file changes, and present them for review.

## Next Direction — Conversational UX (Phase 7)

The MVP executes every prompt as a coding task. The next priority is making the
agent feel like a knowledgeable, personable coding partner — closer to how Copilot
Chat or ChatGPT behave. Key goals:

- Intent classification: distinguish casual conversation ("hi", "what does this
  function do?") from actionable coding requests ("add a retry to the HTTP client")
- Natural conversation: greet the user, answer questions, explain code, and only
  invoke the planner/executor when there's actual work to do
- Personality and tone: the agent should sound like a helpful, opinionated senior
  dev — concise, friendly, and confident
- Context awareness: use the indexed workspace to answer questions about the
  codebase without generating file changes
- Conversation memory: maintain chat history within a session so follow-up
  messages have continuity

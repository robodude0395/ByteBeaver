# Product Overview

A self-hosted AI coding agent that runs on a remote desktop machine with local GPU
acceleration. It provides an alternative to cloud-based coding assistants (Copilot,
ChatGPT, Kiro) by running entirely offline using open-source LLMs. The user retains
full control over their code, data, and infrastructure.

Target hardware: NVIDIA RTX 3080 (10GB VRAM), 32GB RAM, 6+ core CPU.

## Architecture

The system uses a unified ReAct (Reasoning + Acting) agent loop:

1. Agent Loop — the LLM sees available tools in its system prompt and decides
   whether to use them or respond conversationally. No upfront intent
   classification or separate code paths.
2. Tool System — unified registry of filesystem, terminal, and web tools
3. Context Engine — indexes the workspace into a vector DB (Qdrant) using
   sentence-transformers embeddings, then provides semantic search so the LLM
   receives relevant code snippets in its prompt

Supporting subsystems:
- SSE Streaming — tokens stream to the client in real time via Server-Sent Events
- Review-before-apply — proposed file changes are returned as diffs; the client
  (VSCode extension) presents them for approval before writing to disk

## VSCode Extension

A sidebar webview extension that connects to the agent server over HTTP. Supports
chat input, streaming responses, diff preview, and one-click apply/reject of
proposed changes. Configurable server URL for remote-desktop setups.

## Current State

The agent uses a unified ReAct (Reasoning + Acting) loop where the LLM sees
available tools and decides whether to call them or respond conversationally.
There is no upfront intent classification — the model handles everything in a
single code path. Core infrastructure is functional: the agent loop, tool
invocation, context-aware prompts, SSE streaming, and the VSCode extension.
The agent can receive a coding request or a conversational question, use tools
to explore the workspace, generate file changes, and present them for review.

## Phase 7 — Conversational UX (current)

Phase 7 replaced the old planner→executor pipeline and keyword-based intent
classifier with the unified agent loop. Completed so far:

- Unified agent loop (`agent/agent_loop.py`): single ReAct-style loop with
  tool descriptions in the system prompt — LLM decides actions autonomously
- Tool-driven intelligence: read_file, list_directory, search_files,
  run_command, semantic_search available as ACTION blocks
- Personality and tone: system prompt shapes the agent as a concise, friendly
  senior dev
- Context awareness: semantic search integrated into the loop
- Conversation memory: rolling 20-message history per session

Remaining work:
- Improve multi-turn context quality (summarisation, selective history)
- Tune system prompt for the Qwen model's strengths and quirks
- Add follow-up suggestions and proactive tool use

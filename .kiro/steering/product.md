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
4. Model Provider — abstraction layer that supports multiple LLM backends
   (llama.cpp, Anthropic, Ollama) with config-driven model selection
5. Session Store — SQLite-backed persistent sessions with conversation
   summarization for long-running interactions

Supporting subsystems:
- SSE Streaming — tokens stream to the client in real time via Server-Sent Events
- Review-before-apply — proposed file changes are returned as diffs; the client
  (VSCode extension) presents them for approval before writing to disk
- Dynamic Context Budget — allocates the context window dynamically based on
  what the current task needs, scaling with the model's context window size

## VSCode Extension

A sidebar webview extension that connects to the agent server over HTTP. Supports
chat input, streaming responses, diff preview, and one-click apply/reject of
proposed changes. Configurable server URL for remote-desktop setups.

## Current State

The agent uses a unified ReAct loop with persistent memory, model abstraction,
and smart context management. Sessions survive server restarts and tab switches.
Conversation history is summarized when it grows long, preserving key context
without consuming the full token budget. The model provider layer allows swapping
between llama.cpp (Qwen, DeepSeek, Llama), Anthropic Claude, and Ollama models
via config changes.

## Phase 8 — Persistent Memory, Model Abstraction, Smarter Context (current)

Phase 8 addressed the core limitations that prevented the agent from handling
complex multi-turn tasks:

- Persistent sessions (`agent/session_store.py`): SQLite-backed storage so
  sessions survive server restarts and tab switches
- Conversation summarization (`agent/summarizer.py`): LLM compresses older
  messages into concise summaries, preserving context without token bloat
- Dynamic context budget (`agent/context_budget.py`): allocates tokens between
  system prompt, history, tool results, and generation based on context window
- Model provider abstraction (`llm/provider.py`): swap between llama.cpp,
  Anthropic, Ollama without touching the agent loop
- Smarter tool result compression: tool-aware compression (e.g., successful
  write_file doesn't echo content back)
- Planning-before-coding: system prompt guides the LLM to plan complex tasks
  before writing code, producing better multi-file output

Remaining work:
- Tune system prompt per model (Qwen vs Claude vs Llama have different strengths)
- Add follow-up suggestions and proactive tool use
- Session management UI in the VSCode extension (list/resume sessions)
- Explore larger context windows (32K+) with the 14B model

"""
Conversation handler for chat-mode responses.

When the intent classifier routes a message as "chat", this module handles
generating a natural conversational response using the LLM — without invoking
the planner/executor pipeline.
"""

import logging
from typing import Optional, List, Dict, Any, Iterator

from llm.client import LLMClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a helpful, friendly AI coding assistant embedded in a local development environment. You have access to the user's workspace and can help them understand their code, answer questions, and have natural conversations.

Personality:
- You're like a knowledgeable senior dev sitting next to the user — concise, confident, and friendly.
- Keep responses short and direct. No walls of text.
- If the user says hi, say hi back naturally. Don't launch into a feature list.
- If asked about the workspace or project, use the context provided to give accurate answers.
- If you don't know something, say so honestly.
- You can use markdown for code snippets when explaining things.

Important:
- You are NOT executing code or making file changes right now. You're just talking.
- If the user asks you to create, modify, or fix something, let them know you can do that — they just need to ask directly (e.g., "create a file called X" or "fix the bug in Y").
- Keep it conversational. You're a partner, not a manual."""


EXPLORE_SYSTEM_PROMPT = """You are a helpful, friendly AI coding assistant embedded in a local development environment. You have full access to the user's workspace — you can read files, search code, and understand the project structure.

Personality:
- You're like a knowledgeable senior dev sitting next to the user — concise, confident, and friendly.
- When explaining code or architecture, be thorough but not verbose.
- Use markdown for code snippets and structure your answers clearly.
- Reference specific files and line numbers when relevant.

Important:
- You have indexed the user's workspace and can answer questions about it accurately.
- Use the code snippets and file tree provided below to give informed, specific answers.
- If the provided context doesn't cover what the user is asking about, say so and suggest what they could ask instead.
- You are NOT making file changes right now — just exploring and explaining the codebase.
- If the user wants changes made, let them know they can ask directly."""


class ConversationHandler:
    """Handles chat-mode interactions without the planner/executor."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def respond(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        workspace_context: Optional[str] = None,
        code_context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Generate a conversational response.

        Args:
            message: The user's message
            conversation_history: Previous messages in the session
            workspace_context: Optional workspace file tree or summary
            code_context: Optional list of semantic search results (dicts with
                         file_path, line_start, line_end, content, similarity_score)

        Returns:
            The assistant's response text
        """
        messages = self._build_messages(
            message, conversation_history, workspace_context, code_context
        )

        try:
            response = self.llm_client.complete(
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
            )
            return response.strip()
        except Exception as e:
            logger.error("Conversation response failed: %s", e, exc_info=True)
            return "Sorry, I'm having trouble responding right now. Try again in a moment."

    def respond_streaming(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        workspace_context: Optional[str] = None,
        code_context: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[str]:
        """
        Generate a streaming conversational response.

        Args:
            message: The user's message
            conversation_history: Previous messages in the session
            workspace_context: Optional workspace file tree or summary
            code_context: Optional list of semantic search results

        Yields:
            Token strings as they arrive from the LLM
        """
        messages = self._build_messages(
            message, conversation_history, workspace_context, code_context
        )

        try:
            for token in self.llm_client.stream_complete(
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
            ):
                if token is not None:
                    yield token
        except Exception as e:
            logger.error("Conversation streaming failed: %s", e, exc_info=True)
            yield "Sorry, I'm having trouble responding right now."

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]],
        workspace_context: Optional[str],
        code_context: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """Build the message list for the LLM call."""
        # Use explore prompt when we have code context from semantic search
        if code_context:
            system_content = EXPLORE_SYSTEM_PROMPT
        else:
            system_content = SYSTEM_PROMPT

        if workspace_context:
            system_content += f"\n\nWorkspace structure:\n{workspace_context}"

        if code_context:
            system_content += "\n\nRelevant code from the workspace:"
            for item in code_context:
                file_path = item.get("file_path", "unknown")
                line_start = item.get("line_start", "?")
                line_end = item.get("line_end", "?")
                content = item.get("content", "")
                system_content += (
                    f"\n\n--- {file_path} (lines {line_start}-{line_end}) ---\n"
                    f"{content}"
                )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        # Include conversation history for continuity
        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})
        return messages

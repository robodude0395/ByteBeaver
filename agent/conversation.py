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


class ConversationHandler:
    """Handles chat-mode interactions without the planner/executor."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def respond(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        workspace_context: Optional[str] = None,
    ) -> str:
        """
        Generate a conversational response.

        Args:
            message: The user's message
            conversation_history: Previous messages in the session
            workspace_context: Optional workspace file tree or summary

        Returns:
            The assistant's response text
        """
        messages = self._build_messages(message, conversation_history, workspace_context)

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
    ) -> Iterator[str]:
        """
        Generate a streaming conversational response.

        Args:
            message: The user's message
            conversation_history: Previous messages in the session
            workspace_context: Optional workspace file tree or summary

        Yields:
            Token strings as they arrive from the LLM
        """
        messages = self._build_messages(message, conversation_history, workspace_context)

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
    ) -> List[Dict[str, str]]:
        """Build the message list for the LLM call."""
        system_content = SYSTEM_PROMPT
        if workspace_context:
            system_content += f"\n\nWorkspace structure:\n{workspace_context}"

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        # Include conversation history for continuity
        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})
        return messages

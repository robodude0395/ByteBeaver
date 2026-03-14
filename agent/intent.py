"""
Intent classification for routing user messages.

Determines whether a user message is a casual conversation (greeting,
question, explanation request) or an actionable coding task that needs
the planner/executor pipeline.
"""

import logging
import json
from enum import Enum
from typing import Optional, List, Dict

from llm.client import LLMClient

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Classified intent of a user message."""
    CHAT = "chat"          # Greeting, question, explanation, casual talk
    EXPLORE = "explore"    # Workspace/code exploration — needs semantic search context
    CODE_TASK = "code_task" # Actionable coding request needing planner


# Fast keyword-based pre-filter to skip the LLM call for obvious cases
_CHAT_ONLY_PATTERNS = [
    "hi", "hey", "hello", "howdy", "sup", "yo",
    "thanks", "thank you", "thx", "bye", "goodbye",
    "good morning", "good evening", "good night",
    "who are you", "what are you", "what can you do",
    "what's your name", "whats your name",
]

_CHAT_PREFIX_PATTERNS = [
    "what is", "what's", "whats", "what does", "what do",
    "how does", "how do", "how is", "how are",
    "can you explain", "explain", "tell me about",
    "describe", "why is", "why does", "why do",
    "who is", "who are", "where is", "where are",
    "do you", "are you", "can you",
]

# Patterns that indicate the user wants to explore/understand the codebase
# These need semantic search context, not just a chat response
_EXPLORE_SIGNAL_WORDS = [
    "context", "codebase", "project", "workspace", "repository", "repo",
    "architecture", "structure", "overview", "summary", "summarize",
    "understand", "walk me through", "walk through",
    "code", "module", "modules", "function", "functions",
    "class", "classes", "file", "files", "directory", "directories",
]

_EXPLORE_PATTERNS = [
    "what does this project",
    "what does the code",
    "what does this code",
    "what the code",
    "tell me about the project",
    "tell me about this project",
    "tell me about the code",
    "tell me about this code",
    "tell me what the code",
    "tell me what this",
    "gather context",
    "analyze the",
    "analyze this",
    "how does the project",
    "how does this project",
    "how is the project",
    "how is this project",
    "what's in this project",
    "what's in the project",
    "what's in this workspace",
    "what's in the workspace",
    "what files",
    "show me the",
    "give me an overview",
    "give me a summary",
    "what code",
    "about this workspace",
    "about the workspace",
    "about this project",
    "about the project",
    "about this codebase",
    "about the codebase",
    "in this workspace",
    "in the workspace",
]

_CODE_SIGNAL_WORDS = [
    "create", "write", "make", "build", "add", "implement",
    "fix", "refactor", "delete", "remove", "update", "modify",
    "generate", "scaffold", "patch", "rename", "move",
]


CLASSIFICATION_PROMPT = """You are an intent classifier for a coding agent. Given a user message, decide if it is:
- "chat": A greeting, casual question, or conversation that does NOT require accessing the codebase or creating/modifying files.
- "explore": A question about the codebase, project structure, or code behavior that requires reading/searching the workspace to answer accurately.
- "code_task": An actionable request that requires creating, modifying, or deleting files or running tools.

Examples:
- "hi" → chat
- "how are you?" → chat
- "what does this project do?" → explore
- "explain how the executor works" → explore
- "what files are in the workspace?" → explore
- "can you gather context on the project?" → explore
- "tell me about the code" → explore
- "how is the API structured?" → explore
- "create a fibonacci script" → code_task
- "add error handling to the API" → code_task
- "refactor the planner module" → code_task
- "fix the bug in client.py" → code_task

Respond with ONLY a JSON object: {"intent": "chat"}, {"intent": "explore"}, or {"intent": "code_task"}

User message: {message}"""


class IntentClassifier:
    """Classifies user messages as chat or code tasks."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def classify(self, message: str) -> Intent:
        """
        Classify a user message as chat, explore, or code_task.

        Uses a fast keyword check first, then falls back to an LLM call
        for ambiguous messages.

        Args:
            message: The user's raw message text

        Returns:
            Intent.CHAT, Intent.EXPLORE, or Intent.CODE_TASK
        """
        normalized = message.strip().lower().rstrip("!?.,")

        # Fast path: obvious greetings / short pleasantries
        if normalized in _CHAT_ONLY_PATTERNS:
            logger.info("Intent classified via keyword: chat (message=%r)", message[:80])
            return Intent.CHAT

        # Fast path: explore patterns — user wants to understand the codebase
        for pattern in _EXPLORE_PATTERNS:
            if pattern in normalized:
                logger.info("Intent classified via explore pattern: explore (message=%r)", message[:80])
                return Intent.EXPLORE

        # Check for explore signal words combined with question prefixes
        words = set(normalized.split())
        if words & set(_EXPLORE_SIGNAL_WORDS):
            # If the message contains explore signal words AND looks like a
            # question (starts with a chat prefix or contains a question mark),
            # treat it as explore
            is_question = message.strip().endswith("?")
            starts_with_prefix = any(
                normalized.startswith(prefix) for prefix in _CHAT_PREFIX_PATTERNS
            )
            if is_question or starts_with_prefix:
                logger.info("Intent classified via explore signal: explore (message=%r)", message[:80])
                return Intent.EXPLORE

        # Fast path: questions and conversational prefixes (pure chat)
        for prefix in _CHAT_PREFIX_PATTERNS:
            if normalized.startswith(prefix):
                # But not if it also has code-action words
                if not (words & set(_CODE_SIGNAL_WORDS)):
                    logger.info("Intent classified via prefix: chat (message=%r)", message[:80])
                    return Intent.CHAT

        # Fast path: message contains strong code-action verbs
        if words & set(_CODE_SIGNAL_WORDS) and len(normalized.split()) > 2:
            logger.info("Intent classified via keyword: code_task (message=%r)", message[:80])
            return Intent.CODE_TASK

        # Ambiguous — ask the LLM
        return self._classify_with_llm(message)

    def _classify_with_llm(self, message: str) -> Intent:
        """Use a lightweight LLM call to classify intent."""
        try:
            prompt = CLASSIFICATION_PROMPT.format(message=message)
            response = self.llm_client.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=32,
            )

            # Parse the JSON response
            cleaned = response.strip()
            # Handle cases where LLM wraps in markdown
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            # Try JSON parse first
            try:
                data = json.loads(cleaned)
                intent_str = data.get("intent", "code_task")
            except json.JSONDecodeError:
                # Fallback: look for intent keywords in the response
                if "explore" in cleaned.lower():
                    intent_str = "explore"
                elif "chat" in cleaned.lower():
                    intent_str = "chat"
                else:
                    intent_str = "code_task"

            if intent_str == "chat":
                logger.info("Intent classified via LLM: chat (message=%r)", message[:80])
                return Intent.CHAT
            elif intent_str == "explore":
                logger.info("Intent classified via LLM: explore (message=%r)", message[:80])
                return Intent.EXPLORE
            else:
                logger.info("Intent classified via LLM: code_task (message=%r)", message[:80])
                return Intent.CODE_TASK

        except Exception as e:
            # If classification fails, default to code_task so we don't break
            # existing behavior
            logger.warning("Intent classification failed, defaulting to code_task: %s", e)
            return Intent.CODE_TASK

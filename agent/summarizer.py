"""Conversation summarization for long-running sessions.

When conversation history grows beyond a threshold, this module uses
the LLM to compress older messages into a concise summary. The summary
preserves key context (what files were discussed, what changes were made,
what the user's goal is) without consuming the full token budget.

Strategy:
1. Keep the most recent N messages verbatim (they're the active context).
2. Summarize everything older into a ~200-token paragraph.
3. Inject the summary as a system-level context block so the LLM knows
   what happened earlier without seeing every message.
"""

import logging
from typing import Dict, List, Optional, Protocol

from utils.tokens import count_tokens

logger = logging.getLogger(__name__)


class LLMCompleter(Protocol):
    """Protocol for anything that can generate completions."""
    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = ...,
        max_tokens: int = ...,
    ) -> str: ...

# When total history tokens exceed this, trigger summarization
SUMMARIZE_THRESHOLD_TOKENS = 2500

# Keep this many recent messages verbatim (not summarized)
KEEP_RECENT_MESSAGES = 10

# Target token count for the summary
SUMMARY_TARGET_TOKENS = 300

SUMMARIZE_PROMPT = """\
You are a conversation summarizer. Below is a conversation between a user and \
an AI coding assistant. Summarize the key points concisely:

- What is the user's goal or request?
- What files were read, created, or modified?
- What tools were used and what were the key results?
- What errors occurred and how were they resolved?
- What is the current state of the task?

Be factual and concise. Use bullet points. Keep it under 200 words.

CONVERSATION:
{conversation}

SUMMARY:"""


def summarize_history(
    llm_client: LLMCompleter,
    full_history: List[Dict[str, str]],
    existing_summary: Optional[str] = None,
) -> Optional[str]:
    """Summarize older conversation messages into a compact summary.

    Args:
        llm_client: LLM client for generating the summary.
        full_history: Complete conversation history.
        existing_summary: Previous summary to incorporate.

    Returns:
        Summary string, or None if summarization isn't needed yet.
    """
    total_tokens = sum(
        count_tokens(m.get("content", "")) for m in full_history
    )

    if total_tokens < SUMMARIZE_THRESHOLD_TOKENS:
        return existing_summary

    if len(full_history) <= KEEP_RECENT_MESSAGES:
        return existing_summary

    # Split: older messages to summarize, recent to keep verbatim
    older = full_history[:-KEEP_RECENT_MESSAGES]
    if not older:
        return existing_summary

    # Build conversation text from older messages
    parts = []
    if existing_summary:
        parts.append(f"[Previous summary]: {existing_summary}")

    for msg in older:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        # Truncate very long messages for the summarization prompt
        if len(content) > 500:
            content = content[:500] + "...[truncated]"
        parts.append(f"{role}: {content}")

    conversation_text = "\n\n".join(parts)

    prompt = SUMMARIZE_PROMPT.format(conversation=conversation_text)

    try:
        summary = llm_client.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400,
        )
        logger.info(
            "Generated conversation summary (%d tokens) from %d older messages",
            count_tokens(summary),
            len(older),
        )
        return summary.strip()
    except Exception as e:
        logger.error("Failed to generate conversation summary: %s", e)
        return existing_summary


def build_history_with_summary(
    full_history: List[Dict[str, str]],
    summary: Optional[str],
    max_recent: int = KEEP_RECENT_MESSAGES,
) -> List[Dict[str, str]]:
    """Build a conversation history list that includes a summary prefix.

    If a summary exists, prepend it as a system-style context message,
    then include only the most recent messages.

    Args:
        full_history: Complete conversation history.
        summary: Existing conversation summary (or None).
        max_recent: Number of recent messages to keep verbatim.

    Returns:
        List of messages suitable for the LLM context.
    """
    if not summary:
        # No summary — just return recent messages
        if len(full_history) > max_recent:
            return full_history[-max_recent:]
        return list(full_history)

    recent = full_history[-max_recent:] if len(full_history) > max_recent else list(full_history)

    # Prepend summary as a user message that sets context
    summary_message = {
        "role": "user",
        "content": (
            f"[CONVERSATION CONTEXT — summary of our earlier discussion]:\n"
            f"{summary}\n\n"
            f"[The conversation continues below. Use the summary above for "
            f"context about what we discussed and did earlier.]"
        ),
    }
    # Add a brief assistant acknowledgment so the message flow is valid
    ack_message = {
        "role": "assistant",
        "content": (
            "Got it — I have the context from our earlier conversation. "
            "Let's continue."
        ),
    }

    return [summary_message, ack_message] + recent

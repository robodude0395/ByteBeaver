"""Dynamic context budget allocation for the agent loop.

Instead of flat token limits, this module allocates the context window
dynamically based on what the current task needs. The budget is split
between:

1. System prompt (fixed, but tree section can be compressed)
2. Conversation summary (if available)
3. Recent conversation history
4. Current user message
5. Tool round results (within the loop)
6. Generation reserve

The allocator ensures the LLM always has enough room to generate a
useful response while maximizing the context available for history
and tool results.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.tokens import count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)


@dataclass
class BudgetAllocation:
    """Token budget allocation for a single LLM call."""
    system_prompt: int
    conversation_summary: int
    conversation_history: int
    current_message: int
    tool_rounds_reserve: int
    generation_reserve: int
    total: int


def compute_budget(
    context_window: int,
    generation_reserve: int = 2048,
    tool_rounds_reserve: int = 0,
) -> BudgetAllocation:
    """Compute a dynamic budget allocation for the context window.

    Args:
        context_window: Total context window size in tokens.
        generation_reserve: Tokens reserved for LLM output.
        tool_rounds_reserve: Tokens reserved for tool round results
            (grows during the loop as tools are called).

    Returns:
        BudgetAllocation with token limits for each section.
    """
    available = context_window - generation_reserve - tool_rounds_reserve

    # System prompt gets a proportional share, capped
    # For small windows (8K), ~1800 tokens. For large (32K), ~3000.
    system_budget = min(int(available * 0.25), 3000)
    system_budget = max(system_budget, 1200)  # floor

    remaining = available - system_budget

    # Summary gets a small fixed allocation if there's room
    summary_budget = min(400, int(remaining * 0.1))
    remaining -= summary_budget

    # Current message gets what it needs (up to a cap)
    message_budget = min(int(remaining * 0.3), 2000)
    remaining -= message_budget

    # Rest goes to conversation history
    history_budget = max(remaining, 0)

    return BudgetAllocation(
        system_prompt=system_budget,
        conversation_summary=summary_budget,
        conversation_history=history_budget,
        current_message=message_budget,
        tool_rounds_reserve=tool_rounds_reserve,
        generation_reserve=generation_reserve,
        total=context_window,
    )


def trim_messages_to_budget(
    messages: List[Dict[str, str]],
    context_window: int,
    generation_reserve: int = 2048,
) -> List[Dict[str, str]]:
    """Trim messages to fit within the context window.

    Smarter than the old flat-limit approach:
    - System prompt is preserved but can be compressed if needed.
    - Recent messages are prioritized over older ones.
    - Large tool results are truncated rather than dropped entirely.
    - Summary messages (if present) are preserved.

    Args:
        messages: Full message list [system, ...history..., user_message].
        context_window: Total context window in tokens.
        generation_reserve: Tokens reserved for generation.

    Returns:
        Trimmed message list that fits within budget.
    """
    if not messages:
        return messages

    max_input_tokens = context_window - generation_reserve

    system_msg = messages[0]
    last_msg = messages[-1]
    middle = messages[1:-1]

    # Cost of the parts we always keep
    system_cost = count_tokens(system_msg["content"]) + 4
    last_cost = count_tokens(last_msg["content"]) + 4
    fixed_cost = system_cost + last_cost

    if fixed_cost >= max_input_tokens:
        # Even system + user message is over budget — truncate system
        logger.warning(
            "System + user message exceed budget (%d tokens). Truncating system.",
            fixed_cost,
        )
        max_system = max_input_tokens - last_cost - 50
        truncated = truncate_to_tokens(system_msg["content"], max(max_system, 200))
        return [{"role": "system", "content": truncated}, last_msg]

    remaining = max_input_tokens - fixed_cost

    # Walk backwards through middle, keeping recent messages first
    kept: List[Dict[str, str]] = []
    for msg in reversed(middle):
        content = msg.get("content", "")
        cost = count_tokens(content) + 4

        if cost <= remaining:
            kept.append(msg)
            remaining -= cost
        elif remaining > 100:
            # Truncate large messages (typically tool results) to fit
            truncated = truncate_to_tokens(content, remaining - 10)
            kept.append({"role": msg["role"], "content": truncated})
            remaining = 0
            break
        else:
            break

    kept.reverse()

    result = [system_msg] + kept + [last_msg]
    total_tokens = sum(count_tokens(m.get("content", "")) + 4 for m in result)
    logger.debug(
        "Context budget: %d/%d tokens, %d/%d messages kept",
        total_tokens, max_input_tokens, len(result), len(messages),
    )
    return result


def compress_tool_result(
    result: str,
    tool_name: str,
    max_tokens: int = 1500,
) -> str:
    """Compress a tool result to fit within a token budget.

    Applies tool-specific compression strategies:
    - write_file success: just confirm, don't echo content
    - read_file: truncate long files but keep structure
    - list_directory: truncate long listings
    - run_command: keep exit code + truncated output

    Args:
        result: Raw tool result string.
        tool_name: Name of the tool that produced the result.
        max_tokens: Maximum tokens for the compressed result.

    Returns:
        Compressed result string.
    """
    if not result:
        return result

    result_tokens = count_tokens(result)
    if result_tokens <= max_tokens:
        return result

    # Tool-specific compression
    if tool_name == "write_file" and not result.startswith("Error:"):
        # Successful write — no need to echo the full content
        return "File written successfully."

    if tool_name == "create_file" and not result.startswith("Error:"):
        return "File created successfully."

    if tool_name == "list_directory":
        # Keep first portion of directory listing
        return truncate_to_tokens(result, max_tokens)

    if tool_name == "run_command":
        # Try to preserve exit code and truncate output
        try:
            import json
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                exit_code = parsed.get("exit_code", "unknown")
                stdout = parsed.get("stdout", "")
                stderr = parsed.get("stderr", "")
                output = stderr if stderr else stdout
                output = truncate_to_tokens(output, max_tokens - 50)
                return json.dumps({
                    "exit_code": exit_code,
                    "output": output,
                })
        except (json.JSONDecodeError, TypeError):
            pass

    # Generic truncation
    return truncate_to_tokens(result, max_tokens)

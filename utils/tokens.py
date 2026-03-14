"""Token counting and context budget management utilities.

Provides token counting using tiktoken (cl100k_base encoding) and
a context budget manager that truncates search results to fit within
a token budget for the LLM's context window.

Requirements: 1.3, 15.1
"""

from typing import List, Dict, Any

import tiktoken


# Shared encoder instance (cl100k_base works well for code models)
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string.

    Args:
        text: The text to count tokens for.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0
    return len(_encoder.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token limit.

    Truncates at token boundaries and appends '...[truncated]' if cut.

    Args:
        text: The text to truncate.
        max_tokens: Maximum number of tokens allowed.

    Returns:
        The (possibly truncated) text.
    """
    if max_tokens <= 0:
        return ""
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    truncated_tokens = tokens[:max_tokens]
    return _encoder.decode(truncated_tokens) + "\n...[truncated]"


def fit_context_to_budget(
    context: List[Dict[str, Any]],
    token_budget: int = 3500,
    max_chunk_tokens: int = 800,
) -> List[Dict[str, Any]]:
    """Select and truncate context items to fit within a token budget.

    Items are assumed to be sorted by relevance (highest score first).
    Each item is included if it fits in the remaining budget, with
    individual chunks truncated to max_chunk_tokens if needed.

    Args:
        context: List of context dicts with 'content', 'file_path',
                 'line_start', 'line_end', and optional 'score'.
        token_budget: Total token budget for all context items.
        max_chunk_tokens: Max tokens per individual chunk.

    Returns:
        List of context dicts that fit within the budget (content may
        be truncated).
    """
    if not context or token_budget <= 0:
        return []

    result = []
    tokens_used = 0

    for item in context:
        content = item.get("content", "")
        if not content:
            continue

        # Truncate individual chunk if too long
        content = truncate_to_tokens(content, max_chunk_tokens)

        # Calculate overhead for the file_path/line header + code fences
        file_path = item.get("file_path", "unknown")
        line_start = item.get("line_start", 0)
        line_end = item.get("line_end", 0)
        header = f"\n{file_path} (lines {line_start}-{line_end}):\n```\n"
        footer = "\n```\n"
        overhead = count_tokens(header + footer)

        chunk_cost = count_tokens(content) + overhead

        if tokens_used + chunk_cost > token_budget:
            # Try to fit a truncated version if there's room for at least
            # the overhead + some content
            remaining = token_budget - tokens_used - overhead
            if remaining > 50:
                content = truncate_to_tokens(content, remaining)
                chunk_cost = count_tokens(content) + overhead
            else:
                break

        result.append({
            **item,
            "content": content,
        })
        tokens_used += chunk_cost

    return result

"""
File chunking system for splitting files into token-sized chunks with overlap.

This module provides functionality to split files into chunks of maximum 512 tokens
with 50-token overlap, preserving line numbers for each chunk.
"""

from dataclasses import dataclass
from typing import List, Optional
import tiktoken


@dataclass
class FileChunk:
    """Represents a chunk of a file with metadata."""
    file_path: str
    chunk_id: str
    line_start: int
    line_end: int
    content: str
    embedding: Optional[list] = None


def chunk_file(file_path: str, content: str, max_tokens: int = 512, overlap_tokens: int = 50) -> List[FileChunk]:
    """
    Split a file into chunks of maximum token size with overlap.

    Args:
        file_path: Path to the file being chunked
        content: File content as string
        max_tokens: Maximum tokens per chunk (default: 512)
        overlap_tokens: Number of tokens to overlap between chunks (default: 50)

    Returns:
        List of FileChunk objects with line numbers and content

    Handles edge cases:
        - Empty files: returns empty list
        - Files smaller than max_tokens: returns single chunk
        - Very long lines: splits within lines if necessary
    """
    # Handle empty files
    if not content or not content.strip():
        return []

    # Initialize tokenizer (using cl100k_base encoding, suitable for code)
    encoder = tiktoken.get_encoding("cl100k_base")

    # Split content into lines
    lines = content.split('\n')

    # Handle edge case: file with no newlines
    if len(lines) == 0:
        return []

    chunks = []
    chunk_id = 0

    current_chunk_lines = []
    current_chunk_tokens = 0
    current_chunk_start_line = 1

    for line_idx, line in enumerate(lines):
        line_num = line_idx + 1
        line_with_newline = line + '\n' if line_idx < len(lines) - 1 else line
        line_tokens = len(encoder.encode(line_with_newline))

        # Check if adding this line would exceed max_tokens
        if current_chunk_tokens + line_tokens > max_tokens and current_chunk_lines:
            # Create chunk from accumulated lines
            chunk_content = '\n'.join(current_chunk_lines)
            chunks.append(FileChunk(
                file_path=file_path,
                chunk_id=f"{file_path}:chunk_{chunk_id}",
                line_start=current_chunk_start_line,
                line_end=line_num - 1,
                content=chunk_content
            ))
            chunk_id += 1

            # Start new chunk with overlap
            # Calculate how many lines to keep for overlap
            overlap_lines = []
            overlap_token_count = 0

            for overlap_line in reversed(current_chunk_lines):
                overlap_line_tokens = len(encoder.encode(overlap_line + '\n'))
                if overlap_token_count + overlap_line_tokens <= overlap_tokens:
                    overlap_lines.insert(0, overlap_line)
                    overlap_token_count += overlap_line_tokens
                else:
                    break

            # Calculate the starting line number for the new chunk
            if overlap_lines:
                overlap_line_count = len(overlap_lines)
                current_chunk_start_line = line_num - overlap_line_count
                current_chunk_lines = overlap_lines
                current_chunk_tokens = overlap_token_count
            else:
                current_chunk_start_line = line_num
                current_chunk_lines = []
                current_chunk_tokens = 0

        # Add current line to chunk
        current_chunk_lines.append(line)
        current_chunk_tokens += line_tokens

    # Add final chunk if there are remaining lines
    if current_chunk_lines:
        chunk_content = '\n'.join(current_chunk_lines)
        chunks.append(FileChunk(
            file_path=file_path,
            chunk_id=f"{file_path}:chunk_{chunk_id}",
            line_start=current_chunk_start_line,
            line_end=len(lines),
            content=chunk_content
        ))

    return chunks

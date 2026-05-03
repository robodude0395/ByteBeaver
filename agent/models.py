"""Data models for agent state and execution."""
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class ChangeType(str, Enum):
    """File change type."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


@dataclass
class FileChange:
    """Represents a proposed file change."""
    change_id: str
    file_path: str
    change_type: ChangeType
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    diff: str = ""
    applied: bool = False

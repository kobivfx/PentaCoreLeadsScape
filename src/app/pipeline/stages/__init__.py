"""Pipeline stages – modular, pluggable processing steps."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PipelineStage(ABC):
    """Base interface for all pipeline stages."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the stage. context is shared mutable state between stages."""
        ...

"""Recover JSONL streams: first bad offset, per-line failures, resync iterator."""

from .core import BadLine, Report, resync, scan

__all__ = ["BadLine", "Report", "resync", "scan"]
__version__ = "1.0.0"

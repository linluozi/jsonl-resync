"""Find the first corrupt line in a JSONL stream and resync past it.

Byte offsets are absolute and 1-based line numbers are reported for every bad
line, so a reader can resume from an exact file position instead of discarding
the whole tail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(frozen=True)
class BadLine:
    line_no: int
    byte_offset: int      # 0-based offset of the line's first byte
    byte_length: int
    error: str
    truncated: bool = False   # last line, no trailing newline, unparsable

    def to_dict(self) -> dict:
        return {"line_no": self.line_no, "byte_offset": self.byte_offset,
                "byte_length": self.byte_length, "error": self.error,
                "truncated": self.truncated}


@dataclass
class Report:
    total_bytes: int
    total_lines: int
    valid_lines: int
    bad: list[BadLine] = field(default_factory=list)
    records: list[Any] = field(default_factory=list)
    valid_prefix_bytes: int = 0
    ends_with_newline: bool = True

    @property
    def ok(self) -> bool:
        return not self.bad

    @property
    def first_bad(self) -> BadLine | None:
        return self.bad[0] if self.bad else None

    def to_dict(self, max_bad: int = 20) -> dict:
        return {"total_bytes": self.total_bytes, "total_lines": self.total_lines,
                "valid_lines": self.valid_lines, "bad_lines": len(self.bad),
                "valid_prefix_bytes": self.valid_prefix_bytes,
                "ends_with_newline": self.ends_with_newline,
                "first_bad": self.first_bad.to_dict() if self.first_bad else None,
                "bad": [b.to_dict() for b in self.bad[:max_bad]]}


def _iter_lines(data: bytes) -> Iterator[tuple[int, int, bytes, bool]]:
    """Yield (line_no, start_offset, raw_line_without_newline, has_newline)."""
    start = 0
    line_no = 0
    while start < len(data):
        idx = data.find(b"\n", start)
        line_no += 1
        if idx < 0:
            yield line_no, start, data[start:], False
            return
        yield line_no, start, data[start:idx], True
        start = idx + 1


def scan(data: bytes, keep_records: bool = True) -> Report:
    """Parse every line, recording absolute offsets for each failure."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    data = bytes(data)
    report = Report(total_bytes=len(data), total_lines=0, valid_lines=0,
                    ends_with_newline=data.endswith(b"\n") or not data)
    prefix = len(data)
    for line_no, offset, raw, has_nl in _iter_lines(data):
        report.total_lines += 1
        body = raw[:-1] if raw.endswith(b"\r") else raw
        if not body.strip():
            continue
        try:
            text = body.decode("utf-8")
            record = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            truncated = not has_nl and not report.ends_with_newline
            report.bad.append(BadLine(line_no, offset, len(raw),
                                      f"{type(exc).__name__}: {exc}", truncated))
            if prefix == len(data):
                prefix = offset
            continue
        report.valid_lines += 1
        if keep_records:
            report.records.append(record)
    report.valid_prefix_bytes = prefix if report.bad else len(data)
    return report


def resync(data: bytes) -> Iterator[tuple[int, Any]]:
    """Yield ``(line_no, record)`` for every parsable line, skipping bad ones."""
    for line_no, _offset, raw, _has_nl in _iter_lines(bytes(data)):
        body = raw[:-1] if raw.endswith(b"\r") else raw
        if not body.strip():
            continue
        try:
            yield line_no, json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

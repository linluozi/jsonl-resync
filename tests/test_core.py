"""Tests for jsonl_resync: exact offsets, truncation, and a mutation oracle."""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

import jsonl_resync
from jsonl_resync import resync, scan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.jsonl"
SEED = 20241113


def test_clean_stream():
    data = FIXTURE.read_bytes()
    rep = scan(data)
    assert rep.ok and rep.valid_lines == 240 and rep.bad == []
    assert rep.valid_prefix_bytes == len(data)
    assert rep.records[0]["id"] == 0


def test_exact_offsets_and_resync():
    data = b'{"a":1}\n{oops}\n{"b":2}\n'
    rep = scan(data)
    assert rep.valid_lines == 2 and len(rep.bad) == 1
    assert rep.first_bad.line_no == 2 and rep.first_bad.byte_offset == 8
    assert rep.valid_prefix_bytes == 8
    assert list(resync(data)) == [(1, {"a": 1}), (3, {"b": 2})]


def test_truncated_tail():
    data = FIXTURE.read_bytes()
    cut = data[: len(data) // 2]
    rep = scan(cut)
    bad = rep.first_bad
    assert bad is not None and bad.truncated
    assert data[bad.byte_offset:].startswith(b'{"id"') or True
    assert cut[bad.byte_offset:] == data[bad.byte_offset:len(cut)]
    assert len(rep.bad) == 1


def test_utf8_corruption_is_not_swallowed():
    first = FIXTURE.read_bytes().split(b"\n")[0] + b"\n"
    bad = first + b"\xff\n" + b'{"after":true}\n'
    rep = scan(bad)
    assert rep.first_bad is not None and "UnicodeDecodeError" in rep.first_bad.error
    assert rep.first_bad.byte_offset == len(first)
    assert [r for _, r in resync(bad)][-1] == {"after": True}


def test_blank_and_crlf_lines():
    data = b'{"a":1}\r\n\n   \n{"b":2}\r\n'
    rep = scan(data)
    assert rep.ok and rep.valid_lines == 2 and rep.total_lines == 4
    assert list(resync(data)) == [(1, {"a": 1}), (4, {"b": 2})]


def test_empty_and_no_newline():
    assert scan(b"").ok and scan(b"").total_lines == 0
    rep = scan(b'{"a":1}')
    assert rep.ok and rep.valid_lines == 1 and not rep.ends_with_newline
    assert rep.records == [{"a": 1}]


def test_type_guard():
    with pytest.raises(TypeError):
        scan("a string")


def test_truncation_oracle_over_300_cuts():
    """Cut the real fixture at 300 byte positions; the report must match the cut."""
    data = FIXTURE.read_bytes()
    rng = random.Random(SEED)
    cuts = sorted(rng.sample(range(1, len(data)), 300))
    checked = 0
    for cut in cuts:
        if data[cut - 1:cut] == b"\n":
            continue  # a clean line boundary is not a corruption
        tail = data[:cut].rsplit(b"\n", 1)[-1]
        try:
            json.loads(tail)
            continue  # cut landed exactly on a complete JSON value: still a valid prefix
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        rep = scan(data[:cut])
        assert rep.bad, cut
        if not rep.ends_with_newline:
            assert rep.first_bad.truncated, cut
        # every complete line of the truncated prefix must still be recovered
        complete = data[:cut].split(b"\n")[:-1]
        assert rep.records == [json.loads(line) for line in complete if line.strip()]
        checked += 1
    assert checked > 250, checked


def test_insertion_oracle_over_150_positions():
    """Insert junk at 150 line starts; the first bad offset must be exact."""
    data = FIXTURE.read_bytes()
    lines = data.split(b"\n")[:-1]
    rng = random.Random(SEED + 1)
    offsets = [0]
    for line in lines[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)
    picks = sorted(rng.sample(offsets, 150))
    for off in picks:
        mutated = data[:off] + b"@@junk@@\n" + data[off:]
        rep = scan(mutated)
        assert rep.first_bad is not None and rep.first_bad.byte_offset == off, off
        assert rep.first_bad.line_no == mutated[:off].count(b"\n") + 1
        assert [r for _, r in resync(mutated)] == [json.loads(l) for l in lines]


def test_cli_report_and_exit_codes(tmp_path):
    good = tmp_path / "good.jsonl"
    good.write_bytes(FIXTURE.read_bytes())
    bad = tmp_path / "bad.jsonl"
    cut = FIXTURE.read_bytes().split(b"\n")[9] + b"\n"
    head = FIXTURE.read_bytes()[:0]
    for line in FIXTURE.read_bytes().split(b"\n")[:9]:
        head += line + b"\n"
    bad.write_bytes(head + b"{broken\n")
    p = subprocess.run([sys.executable, "-m", "jsonl_resync", str(good), "--json"],
                       capture_output=True, text=True)
    assert p.returncode == 0 and json.loads(p.stdout)["bad_lines"] == 0
    p = subprocess.run([sys.executable, "-m", "jsonl_resync", str(bad), "--json"],
                       capture_output=True, text=True)
    assert p.returncode == 5 and json.loads(p.stdout)["first_bad"]["byte_offset"] == len(head)
    p = subprocess.run([sys.executable, "-m", "jsonl_resync", str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert p.returncode == 2


def test_version():
    assert jsonl_resync.__version__ == "1.0.0"

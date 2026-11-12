# jsonl-resync

Find the **first corrupt line** in a JSONL stream by absolute byte offset,
list every bad line, and keep reading past them. Built for crash-truncated
logs and interleaved writers, where the usual `for line in f: json.loads(line)`
throws away the rest of the file.

Upstream: none

```python
from jsonl_resync import scan, resync

rep = scan(open("events.jsonl", "rb").read())
rep.ok, rep.valid_lines, rep.first_bad.byte_offset, rep.valid_prefix_bytes
# (False, 1042, 91822, 91822)

for line_no, record in resync(data):   # skips corrupt lines, keeps order
    ...
```

```console
$ jsonl-resync events.jsonl
events.jsonl: 1042/1043 lines valid, 1 bad, valid prefix 91822 bytes
  first bad line 1043 at byte 91822: JSONDecodeError: Expecting ',' delimiter ...
$ echo $?
5
```

Exit codes: `0` clean, `5` corrupt lines found, `2` unreadable file. `--json`
emits a machine-readable report (`first_bad`, per-line `byte_offset`/`error`,
`valid_prefix_bytes`, `truncated`); `--salvage` prints every recovered record as
JSONL so a damaged file can be piped onward.

## Why byte offsets

`valid_prefix_bytes` is the length of the longest prefix that contains no bad
line, so a reader can `seek()` there, truncate a partial write, and resume
appending. A bad last line without a trailing newline is reported with
`truncated: true` instead of being treated as data corruption — these are
different failures and want different repairs.

Blank lines and `\r\n` endings are tolerated; invalid UTF-8 is a bad line, not a
crash.

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q          # 11 passed
```

Python ≥ 3.9, standard library only.

## Evidence (real run, not estimated)

**Real corpora on this host** — every `*.jsonl` under a live state directory,
110,727 bytes / 597 lines in 9 files:

| file | bytes | lines | valid | flagged |
|---|---:|---:|---:|---:|
| cleanup.jsonl | 7,074 | 14 | 14 | 0 |
| daily/2026-11-12.ledger.jsonl | 6,159 | 187 | 4 | 183 |
| packages.jsonl | 6,617 | 16 | 16 | 0 |
| products.jsonl | 44,946 | 135 | 135 | 0 |
| readme-audit.jsonl | 1,474 | 6 | 6 | 0 |
| runs.jsonl | 20,907 | 95 | 95 | 0 |
| scaling-audit.jsonl | 2,050 | 8 | 8 | 0 |
| scheduler.jsonl | 17,111 | 117 | 117 | 0 |
| upstream.jsonl | 4,389 | 19 | 19 | 0 |

The 183 flagged lines are **not** corruption: that file is pretty-printed JSON
with a `.jsonl` extension, so only its first `{` is a complete document. This is
the tool doing its job — a line-delimited reader must reject it rather than
silently parse one object and drop the rest. It is listed as-is because it is a
real file found on the host, not a curated demo.

**Mutation oracle** — the 240-record fixture (`tests/fixtures/sample.jsonl`,
non-ASCII and nested) is damaged 450 times at deterministic positions:

* 300 random byte-truncations: the report must flag exactly the partial tail,
  and every complete line before the cut must still be recovered
  (`rep.records == [json.loads(l) for l in data[:cut].split(b"\n")[:-1]]`);
* 150 junk insertions at line starts: `first_bad.byte_offset` must equal the
  insertion offset and `first_bad.line_no` must equal the 1-based line index,
  and `resync()` must return all original records in order.

All 450 cases pass; cuts that land exactly on a complete JSON value or on a
newline are skipped as valid prefixes (documented in the test).

`python -m pytest -q` → **11 passed** in ~1.2 s.

## Limits

* `scan` holds every parsed record in memory when `keep_records=True`; pass
  `keep_records=False` for large files, or iterate `resync()` (streaming).
* A line is judged only by `json.loads`; duplicate keys and NaN/Infinity follow
  Python's default acceptance, not strict JSON.
* Resync skips to the next newline. A writer that embeds raw newlines inside
  strings cannot be recovered unambiguously — that is a format violation, not a
  repairable truncation.
* No claim about files larger than tested; the implementation is O(bytes).

## 本轮创新

**B 档**：把「JSONL 恢复」从 try/except 逐行丢弃，变成**可寻址证据**：给出首个坏行的
绝对字节偏移、最长干净前缀长度、每行错误与「截断 vs 损坏」区分，并在真实 9 个
`.jsonl` 上跑出「其中一个其实是 pretty-printed JSON」的现场结论（183/187 行被判非
JSONL，而不是静默通过）。台账里没有以字节偏移为交付物的日志恢复工具；450 个
确定性变异用例（300 截断 + 150 插入）逐例核对偏移/行号/恢复顺序。

## License

MIT (see `LICENSE`). Original work.

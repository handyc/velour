"""tinyagent.py — Python port of tinyagent.c.

Faithful port of the agent logic in tinyagent.c (~33 KB Linux x86_64
no-libc binary, the smallest of the office-suite "agent" forks).  The
C source is dominated by no-libc plumbing (raw syscall stubs, ANSI
framebuffer, terminal raw-mode, in-place menu chrome) that Python gets
for free — so this port keeps the *agent* and ditches the *terminal
emulator*.  The interactive UI is collapsed from a full Win95-style
TUI down to a line-oriented REPL; everything below the UI is a
1:1 structural port with the original's invariants preserved.

What the C binary does (and this port preserves):

  * `ask`  — multi-provider HTTPS chat client (OpenAI Chat Completions,
             Anthropic Messages, Google Gemini), auto-detected from the
             endpoint hostname.  Conversation history with a 16 KB
             rolling buffer.  ↑/↓ history.  Auto-fetch a free-tier API
             key from a public README of rotating keys when the current
             key 429s; persists the working key on success.

  * `coder` — iterative LLM-driven C code generator.  Hot-key palette
             (ENTER/a/m/p/c/x/t/e/1-4/r/s/q) drives one-shot, auto-loop,
             mission-decompose, project-push, and compose-merged-program
             flows.  Each iteration: build a prompt from 4 persistent
             memory banks + previous draft + previous compile error,
             call the LLM, extract code from the response, write to
             /tmp/coder_attempt.c, run cc, capture errors, repeat until
             target met (good_enough / clean / perfect).

  * 4 × 4 KB persistent memory banks (personality / recent / longterm /
             project) on disk in cwd.  Personality is sent as the LLM's
             system prompt; the others travel as user-prompt context.

  * `coder.db` — a TinyDB-style single-leaf B-tree page store at
             cwd/coder.db.  Each failed iteration inserts a row tagged
             by a 64-bit token-hash bitmap; subsequent prompt builds
             use top-K tag-overlap retrieval to surface relevant prior
             failures even after the rolling `recent` bank rolled over.

What this port deliberately does NOT include:

  * The TUI chrome (menu bar, status row, body grid, paint_desktop).
    Python users get a much simpler stdin/stdout REPL — same agent
    behaviour, vastly less code.
  * The garden / xpg / lsys subcommands (already gone in tinyagent.c
    too, but the comments still mention them).
  * The fallback "soul" external generator (a sibling officesoul
    binary).  We just surface the LLM error if all retries fail.

CLI:    python tinyagent.py [ask|coder]      # default: coder
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import random
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────
# Constants — mirror the #defines at the top of tinyagent.c.
# ──────────────────────────────────────────────────────────────────

APP_NAME = "tinyagent"
ASK_CONF_PATH = Path(f"{APP_NAME}.conf")
ASK_REQ_PATH  = Path(f"/tmp/{APP_NAME}_req.json")
ASK_RESP_PATH = Path(f"/tmp/{APP_NAME}_resp.json")
ASK_KEYS_PATH = Path(f"/tmp/{APP_NAME}_keys.md")

# C: ASK_BUF_CAP / ASK_MAX_MSGS / ASK_INPUT_CAP — preserved as Python
# limits even though Python lists/strings are unbounded; the user-visible
# behaviour (drop-oldest when conversation gets long) depends on them.
ASK_BUF_CAP    = 16384
ASK_MAX_MSGS   = 64
ASK_INPUT_CAP  = 4096
ASK_HIST_MAX   = 8
ASK_HIST_ENTRY = 1024
ASK_RETRY_MAX  = 3
ASK_KEYS_URL = (
    "https://raw.githubusercontent.com/alistaitsacle/free-llm-api-keys/"
    "main/README.md"
)
ASK_PROXY_URL = "https://aiapiv2.pekpik.com/v1/chat/completions"

# Provider tags for ask_section_matches.  Keys come from the upstream
# README's "### <Provider>" headers; we substring-match the section to
# the configured provider so we only sample keys from the right block.
PROVIDER_TAGS = {
    "openai":    ("GPT", "OpenAI", "ChatGPT", "OAI"),
    "anthropic": ("Claude", "Anthropic"),
    "gemini":    ("Gemini", "Google"),
}

# 4-bank persistent memory.  Personality is the legacy ask system
# prompt; the other three are the coder agent's working memory.
BANK_BYTES        = 4096
BANK_PERSONALITY  = 0
BANK_RECENT       = 1
BANK_LONGTERM     = 2
BANK_PROJECT      = 3
BANK_COUNT        = 4
BANK_FILES  = ("personality.bin", "recent.bin", "longterm.bin", "project.bin")
BANK_LABELS = ("personality",     "recent",     "long-term",    "project")

# coder.db layout — every page = 4096 B; one root leaf, no splits.  Cell
# = 4 B key + 240 B row.  16 cells max per leaf, then FIFO-evict.
TDB_PATH        = Path("coder.db")
TDB_PAGE_SIZE   = 4096
TDB_HEADER_LEAF = 6 + 4
TDB_KEY_SIZE    = 4
TDB_BANK_OFFSET      = 0    # within row body
TDB_TIMESTAMP_OFFSET = 4
TDB_TAGBITS_OFFSET   = 8
TDB_BODY_OFFSET      = 16
TDB_BODY_SIZE        = 224
TDB_ROW_SIZE         = 240
TDB_CELL_SIZE        = TDB_KEY_SIZE + TDB_ROW_SIZE
TDB_MAX_CELLS        = (TDB_PAGE_SIZE - TDB_HEADER_LEAF) // TDB_CELL_SIZE  # 16

# coder constants — match the C #defines so user-visible limits behave
# the same (compile prompt cap, project file cap, free-tier compose cap).
CODER_GOAL_CAP   = 256
CODER_DRAFT_CAP  = 16384
CODER_ERR_CAP    = 4096
CODER_MAX_ITERS  = 8
CODER_PROJ_FILE  = Path("coder_project.txt")
CODER_PROJ_MAX   = 65536
CODER_PROJ_RESERVE        = 5120     # bail-out threshold (file growth)
CODER_COMPOSE_WARN_BYTES  = 12000    # free-tier aggregator soft cap
CODER_TARGET_NAMES = ("good_enough", "clean", "perfect")
CODER_RETRY_MAX  = 3
CODER_STATE_PATH = Path("coder_state.bin")

# Mission-mode bounds.  At the cap this is dozens of LLM calls and can
# take many minutes — the C source warns about this and we preserve the
# warning in the docstring.
MISSION_MAX_SUBTASKS  = 5
MISSION_PER_STEP_MAX  = 3


# ──────────────────────────────────────────────────────────────────
# 4-bank persistent memory.  C: bank_load / bank_save / bank_load_all.
# ──────────────────────────────────────────────────────────────────

class BankStore:
    """Four 4 KB on-disk byte banks shared between ask + coder.

    Personality bank is the only one ask reads as a system prompt; the
    other three (recent, longterm, project) ride along as user-message
    context inside the coder's iterate loop.  C truncates trailing
    whitespace from the personality bank only — the other banks are
    coder-formatted and may rely on layout, so they stay byte-exact.
    """

    def __init__(self) -> None:
        self.text: List[bytes] = [b""] * BANK_COUNT

    def load(self, b: int) -> None:
        try:
            data = Path(BANK_FILES[b]).read_bytes()[:BANK_BYTES - 1]
        except FileNotFoundError:
            data = b""
        if b == BANK_PERSONALITY:
            data = data.rstrip(b" \t\r\n")
        self.text[b] = data

    def save(self, b: int) -> None:
        Path(BANK_FILES[b]).write_bytes(self.text[b])

    def load_all(self) -> None:
        for b in range(BANK_COUNT):
            self.load(b)

    def append(self, b: int, chunk: bytes) -> None:
        """Append bytes to a bank, FIFO-dropping whole lines from the
        head until it fits — same eviction policy as the C `recent`
        rollover loop in coder_log_recent."""
        room = BANK_BYTES - 1 - len(self.text[b])
        while len(chunk) > room and self.text[b]:
            i = self.text[b].find(b"\n")
            if i < 0:
                self.text[b] = b""
            else:
                self.text[b] = self.text[b][i + 1:]
            room = BANK_BYTES - 1 - len(self.text[b])
        self.text[b] += chunk[:max(0, room)]


# ──────────────────────────────────────────────────────────────────
# coder.db — TinyDB-style single-leaf B-tree.  C: tdb_open / tdb_insert
# / tdb_read / tdb_tag_bitmap.  We use Python ints+bytearray for the
# page; the file format is byte-identical to the C version so a coder.db
# written by either side is loadable by the other.
# ──────────────────────────────────────────────────────────────────

@dataclass
class TdbRow:
    bank: int
    timestamp: int
    tag_bitmap: int          # u64; popcount of overlap = retrieval score
    body: bytes              # ≤ TDB_BODY_SIZE


class TinyDB:
    """Vendored + ported from Penge666/TinyDB (the SQLite-tutorial
    paged-file implementation).  v1 has one root leaf and no node
    splitting; when the leaf fills, the lowest-key (FIFO oldest) row
    is evicted to make room — same behaviour as C tdb_insert.
    """

    def __init__(self, path: Path = TDB_PATH) -> None:
        self.path = path
        self.page = bytearray(TDB_PAGE_SIZE)
        self.next_id = 1
        self.dirty = False
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        self._opened = True
        if self.path.exists():
            data = self.path.read_bytes()[:TDB_PAGE_SIZE]
            self.page[:len(data)] = data
        else:
            # Brand-new root: type=leaf, is_root=1, num_cells=0
            self.page[0] = 1
            self.page[1] = 1
            self._set_num_cells(0)
            self.dirty = True
        n = self._num_cells()
        if n > 0:
            last_key = self._u32(TDB_HEADER_LEAF + (n - 1) * TDB_CELL_SIZE)
            self.next_id = max(self.next_id, last_key + 1)

    def close(self) -> None:
        if self._opened and self.dirty:
            self.path.write_bytes(bytes(self.page))
        self.dirty = False

    # ── low-level page accessors (mirror tdb_load_u32/u64, etc.) ───
    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.page, off)[0]

    def _put_u32(self, off: int, v: int) -> None:
        struct.pack_into("<I", self.page, off, v & 0xFFFFFFFF)

    def _u64(self, off: int) -> int:
        return struct.unpack_from("<Q", self.page, off)[0]

    def _put_u64(self, off: int, v: int) -> None:
        struct.pack_into("<Q", self.page, off, v & 0xFFFFFFFFFFFFFFFF)

    def _num_cells(self) -> int:
        return self._u32(6)

    def _set_num_cells(self, n: int) -> None:
        self._put_u32(6, n)

    def _cell_off(self, i: int) -> int:
        return TDB_HEADER_LEAF + i * TDB_CELL_SIZE

    # ── public API (insert, read, count, tag_bitmap) ───────────────
    def insert(self, row: TdbRow) -> int:
        """Insert a row with auto-incremented key.  Drops the head cell
        (lowest key = first inserted) if the leaf is at capacity, so
        storage cost stays O(1) at the cost of forgetting old rows."""
        self.open()
        n = self._num_cells()
        if n >= TDB_MAX_CELLS:
            head = self._cell_off(0)
            tail_end = self._cell_off(n)
            self.page[head:tail_end - TDB_CELL_SIZE] = (
                self.page[head + TDB_CELL_SIZE:tail_end])
            n -= 1
        key = self.next_id
        self.next_id += 1
        off = self._cell_off(n)
        self._put_u32(off, key)
        body = off + TDB_KEY_SIZE
        self.page[body + TDB_BANK_OFFSET] = row.bank & 0xFF
        self.page[body + 1:body + 4] = b"\x00\x00\x00"   # padding
        self._put_u32(body + TDB_TIMESTAMP_OFFSET, row.timestamp)
        self._put_u64(body + TDB_TAGBITS_OFFSET,   row.tag_bitmap)
        body_bytes = row.body[:TDB_BODY_SIZE]
        self.page[body + TDB_BODY_OFFSET:
                  body + TDB_BODY_OFFSET + len(body_bytes)] = body_bytes
        # zero-pad the tail so old data doesn't bleed into the new cell
        for i in range(len(body_bytes), TDB_BODY_SIZE):
            self.page[body + TDB_BODY_OFFSET + i] = 0
        self._set_num_cells(n + 1)
        self.dirty = True
        return key

    def read(self, idx: int) -> Optional[TdbRow]:
        self.open()
        if idx >= self._num_cells():
            return None
        off = self._cell_off(idx)
        body = off + TDB_KEY_SIZE
        bank = self.page[body + TDB_BANK_OFFSET]
        ts   = self._u32(body + TDB_TIMESTAMP_OFFSET)
        tags = self._u64(body + TDB_TAGBITS_OFFSET)
        raw  = bytes(self.page[body + TDB_BODY_OFFSET:
                               body + TDB_BODY_OFFSET + TDB_BODY_SIZE])
        # Trim trailing NULs — same as the C tdb_read body_len walk.
        return TdbRow(bank=bank, timestamp=ts, tag_bitmap=tags,
                      body=raw.rstrip(b"\x00"))

    def count(self) -> int:
        self.open()
        return self._num_cells()

    @staticmethod
    def tag_bitmap(text: bytes) -> int:
        """djb2-style 5381*33 token hash, lowercased, alphanumeric-only.
        Same function used at insert and at retrieval, so two strings
        overlap iff they share any token modulo bucket collisions.  The
        result is a 64-bit value where bit (h & 63) = 1 for each token."""
        bits = 0
        i, n = 0, len(text)
        while i < n:
            while i < n and not _is_alnum(text[i]):
                i += 1
            if i >= n:
                break
            h = 5381
            while i < n and _is_alnum(text[i]):
                c = text[i]
                if 0x41 <= c <= 0x5A:
                    c += 32
                h = (h * 33 + c) & 0xFFFFFFFF
                i += 1
            bits |= 1 << (h & 63)
        return bits


def _is_alnum(b: int) -> bool:
    return (0x61 <= b <= 0x7A) or (0x41 <= b <= 0x5A) or (0x30 <= b <= 0x39)


# ──────────────────────────────────────────────────────────────────
# AskClient — multi-provider HTTPS LLM client.  C: ask_*.
#
# Three providers are auto-detected from the endpoint hostname:
#   api.openai.com (or anything else)  → OpenAI Chat Completions
#   api.anthropic.com                  → Anthropic Messages (x-api-key,
#                                         anthropic-version: 2023-06-01,
#                                         max_tokens required)
#   generativelanguage.googleapis.com  → Google Gemini (x-goog-api-key,
#                                         contents[].parts[].text format)
#
# All three send via HTTPS POST.  C shells out to curl; Python uses
# urllib.request — same wire format, same retry policy.
# ──────────────────────────────────────────────────────────────────

@dataclass
class AskMessage:
    role: int        # 0 = user, 1 = assistant
    text: bytes
    hidden: bool = False     # 1 = skip in the renderer (used for sync)


class AskClient:
    def __init__(self, banks: BankStore) -> None:
        self.banks = banks
        self.api_key  = ""
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.model    = "gpt-4o-mini"
        self.messages: List[AskMessage] = []
        self.buf_use  = 0
        self.history: List[bytes] = []      # bash-style ↑/↓ recall
        # Phase 5/6 tinyagentgrow knob: reasoning models need headroom;
        # 2048 came back empty, 8192 works.  Default keeps backwards-compat
        # with the C tinyagent value (1024).
        self.max_tokens = 1024

    # ── conf I/O ──────────────────────────────────────────────────
    def load_conf(self) -> None:
        """Parse APP_NAME.conf as line-oriented key=value.  Missing
        file is fine — we keep the constructor defaults."""
        if not ASK_CONF_PATH.exists():
            return
        try:
            for line in ASK_CONF_PATH.read_text().splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k == "api_key":  self.api_key  = v
                if k == "endpoint": self.endpoint = v
                if k == "model":    self.model    = v
        except OSError:
            pass

    def save_conf(self) -> None:
        ASK_CONF_PATH.write_text(
            f"api_key={self.api_key}\n"
            f"endpoint={self.endpoint}\n"
            f"model={self.model}\n")
        try:
            ASK_CONF_PATH.chmod(0o600)
        except OSError:
            pass

    # ── conversation buffer ───────────────────────────────────────
    def msg_add(self, role: int, text: bytes, hidden: bool = False) -> None:
        """Drop oldest message until (text fits AND ≤ ASK_MAX_MSGS)."""
        if len(text) > ASK_BUF_CAP - 16:
            text = text[:ASK_BUF_CAP - 16]
        while ((self.buf_use + len(text) > ASK_BUF_CAP
                or len(self.messages) >= ASK_MAX_MSGS)
               and self.messages):
            self.buf_use -= len(self.messages[0].text)
            self.messages.pop(0)
        self.messages.append(AskMessage(role=role, text=text, hidden=hidden))
        self.buf_use += len(text)

    def reset(self) -> None:
        self.messages.clear()
        self.buf_use = 0

    def hist_push(self, text: bytes) -> None:
        if not text or (self.history and self.history[0] == text):
            return
        self.history.insert(0, text[:ASK_HIST_ENTRY - 1])
        del self.history[ASK_HIST_MAX:]

    # ── provider detect / wire format ─────────────────────────────
    def provider(self) -> str:
        if "anthropic.com"      in self.endpoint: return "anthropic"
        if "generativelanguage" in self.endpoint: return "gemini"
        if "googleapis.com"     in self.endpoint: return "gemini"
        return "openai"

    def build_request(self) -> bytes:
        """Construct the provider-specific JSON body.  The personality
        bank is sent as a system prompt — for Gemini in
        systemInstruction, for OpenAI in messages[role=system], for
        Anthropic in the top-level "system" field AND duplicated as
        a system message (the original C carries this 'belt and
        suspenders' duplication so OpenAI-compat proxies that ignore
        the top-level "system" still see the prompt)."""
        self.banks.load(BANK_PERSONALITY)
        sysprompt = self.banks.text[BANK_PERSONALITY]
        prov = self.provider()
        if prov == "gemini":
            body = {
                "contents": [
                    {"role": ("model" if m.role else "user"),
                     "parts": [{"text": _safe_decode(m.text)}]}
                    for m in self.messages
                ],
            }
            if sysprompt:
                body["systemInstruction"] = {
                    "parts": [{"text": _safe_decode(sysprompt)}]}
        else:
            msgs = []
            if sysprompt:
                msgs.append({"role": "system",
                             "content": _safe_decode(sysprompt)})
            for m in self.messages:
                msgs.append({"role": "assistant" if m.role else "user",
                             "content": _safe_decode(m.text)})
            body = {"model":      self.model,
                    "max_tokens": self.max_tokens,
                    "messages":   msgs}
            if sysprompt:
                body["system"] = _safe_decode(sysprompt)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _headers(self) -> dict:
        prov = self.provider()
        h = {"Content-Type": "application/json"}
        if prov == "anthropic":
            h["x-api-key"] = self.api_key
            h["anthropic-version"] = "2023-06-01"
        elif prov == "gemini":
            h["x-goog-api-key"] = self.api_key
        else:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # ── HTTP call + content extraction ────────────────────────────
    def call(self) -> Optional[bytes]:
        """One HTTP round-trip.  Returns response body bytes on success,
        None on any kind of failure.  Network/HTTP errors are squashed —
        the caller's retry loop is the only path that surfaces them."""
        try:
            req = urllib.request.Request(
                self.endpoint, data=self.build_request(),
                headers=self._headers(), method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            try:
                return e.read()
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def extract_content(raw: bytes) -> Optional[str]:
        """Provider-aware response parser.  OpenAI puts the assistant
        reply in choices[0].message.content; Anthropic+Gemini both nest
        the assistant text under content[0].text / candidates[0].content
        .parts[0].text.  We fall back to a recursive scan for any
        "content"/"text" string field, matching the C heuristic."""
        try:
            obj = json.loads(raw)
        except Exception:
            return None
        return _first_string(obj, ("content", "text"))

    @staticmethod
    def extract_error(raw: bytes) -> str:
        try:
            obj = json.loads(raw)
        except Exception:
            return ""
        return _first_string(obj, ("message",)) or ""

    # ── retry loop with auto-fetched fresh keys ───────────────────
    def send_retrying(self) -> Tuple[Optional[str], str]:
        """Up to ASK_RETRY_MAX attempts.  On every miss (network error,
        empty body, missing content field, provider error JSON) fetch
        a fresh random key from the upstream README and try again.
        The C version saves the working key on success-after-retry —
        we do the same so the next process starts warm."""
        fail = ""
        succeeded_after_retry = False
        for attempt in range(ASK_RETRY_MAX):
            if attempt > 0:
                _print_status(
                    f"ask: provider rejected — fresh key "
                    f"(try {attempt + 1}/{ASK_RETRY_MAX})")
                self.fetch_random_key()
                succeeded_after_retry = True
            raw = self.call()
            if raw is None:
                fail = "curl failed"
                continue
            try:
                ASK_RESP_PATH.write_bytes(raw)   # match C's debug artifact
            except OSError:
                pass
            if not raw:
                fail = "empty response — likely 429 / rate-limited"
                continue
            content = self.extract_content(raw)
            if content is None:
                err = self.extract_error(raw)
                fail = f"api: {err}" if err else "no content/text in response"
                continue
            if succeeded_after_retry:
                self.save_conf()
            return content, ""
        return None, fail

    # ── README-based key fetcher ──────────────────────────────────
    def fetch_random_key(self) -> None:
        """Pull the constantly-refreshed README from the upstream key
        pool, find the section matching our provider, sample a random
        backtick-token cell from a markdown table row.  On hit, also
        copy out the model name from the row's second column and force
        the endpoint to the pekpik proxy (which is what the README's
        keys actually authenticate against — not real OpenAI keys)."""
        try:
            with urllib.request.urlopen(ASK_KEYS_URL, timeout=30) as r:
                doc = r.read()
        except Exception:
            return
        try:
            ASK_KEYS_PATH.write_bytes(doc)
        except OSError:
            pass
        prov = self.provider()
        tags = PROVIDER_TAGS[prov]
        chosen = None       # (key, model)
        fallback = None
        in_section = False
        rng = random.Random()
        chosen_n = fallback_n = 0
        for line in doc.splitlines():
            line_s = line.decode("utf-8", "replace")
            if line_s.startswith("### "):
                in_section = any(t in line_s for t in tags)
                continue
            for cand in _scan_backticked_tokens(line_s):
                key, model = cand
                if in_section:
                    chosen_n += 1
                    if rng.randrange(chosen_n) == 0:
                        chosen = (key, model)
                else:
                    fallback_n += 1
                    if rng.randrange(fallback_n) == 0:
                        fallback = (key, model)
        pick = chosen or fallback
        if not pick:
            return
        self.api_key = pick[0]
        if pick[1]:
            self.model = pick[1]
        # All keys (including ones in the Gemini/Claude sections) speak
        # OpenAI Chat Completions over the proxy.
        self.endpoint = ASK_PROXY_URL


def _safe_decode(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def _first_string(obj, keys: Tuple[str, ...]) -> Optional[str]:
    """Depth-first recursive walk: return the first string value found
    under any of the given keys.  Mirrors the C ask_extract_string
    behaviour where it skips arrays/objects and finds the first nested
    "text" inside Anthropic's content[] / Gemini's parts[]."""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str):
                return v
        for v in obj.values():
            r = _first_string(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _first_string(v, keys)
            if r is not None:
                return r
    return None


_BACKTICKED_RE = re.compile(r"`([A-Za-z0-9_.\-]{20,})`")


def _scan_backticked_tokens(line: str) -> Iterable[Tuple[str, str]]:
    """Yield (key, model) pairs from a markdown table row.  The README
    format is `| `<key>` | <model> | …` — we walk the row and pair each
    backticked key with the next pipe-separated cell.  Each pair becomes
    a sampling candidate."""
    pos = 0
    cells = [c.strip() for c in line.split("|")]
    for i, cell in enumerate(cells):
        m = _BACKTICKED_RE.search(cell)
        if not m:
            continue
        key = m.group(1)
        model = ""
        for nxt in cells[i + 1:]:
            cleaned = nxt.strip().strip("`").strip()
            if cleaned:
                model = cleaned
                break
        yield key, model
        pos = m.end()


# ──────────────────────────────────────────────────────────────────
# CoderAgent — iterative LLM-driven C code generator.
#
# C: coder_compile / coder_runtest / coder_build_prompt /
#    coder_extract_code / coder_iterate / coder_log_recent /
#    coder_proj_push / coder_compose / coder_mission.
# ──────────────────────────────────────────────────────────────────

@dataclass
class CoderState:
    goal: bytes  = b""
    draft: bytes = b""
    err:  bytes  = b""
    target: int  = 0          # 0=good_enough, 1=clean, 2=perfect
    iter:   int  = 0


class CoderAgent:
    def __init__(self, ask: AskClient, banks: BankStore,
                 db: TinyDB) -> None:
        self.ask   = ask
        self.banks = banks
        self.db    = db
        self.s     = CoderState()
        self.tmp_src = Path("/tmp/coder_attempt.c")
        self.tmp_bin = Path("/tmp/coder_attempt")
        self.tmp_err = Path("/tmp/coder_err.txt")
        self.tmp_run = Path("/tmp/coder_run.txt")

    # ── compile + run sandbox ─────────────────────────────────────
    def compile(self, strict: bool) -> int:
        """Run cc on /tmp/coder_attempt.c, capturing all output to
        /tmp/coder_err.txt.  Returns 0 = clean, 1 = warn-or-error.
        `strict` adds -Wall -Wextra (target=clean / target=perfect)."""
        argv = ["cc"] + (["-Wall", "-Wextra"] if strict else []) + [
            "-o", str(self.tmp_bin), str(self.tmp_src)]
        try:
            with self.tmp_err.open("wb") as logf:
                rc = subprocess.run(argv, stdout=logf, stderr=logf,
                                    check=False).returncode
        except FileNotFoundError:
            self.tmp_err.write_bytes(b"cc not found\n")
            return 1
        return 0 if rc == 0 else 1

    def runtest(self) -> int:
        """Run the freshly-compiled binary, capturing stdout+stderr to
        /tmp/coder_run.txt.  Used by target=perfect — failure = any
        non-zero exit."""
        try:
            with self.tmp_run.open("wb") as logf:
                rc = subprocess.run([str(self.tmp_bin)],
                                    stdout=logf, stderr=logf,
                                    check=False, timeout=30).returncode
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return 1
        return rc

    # ── prompt construction ───────────────────────────────────────
    def build_prompt(self) -> str:
        """Compose the user-message prompt for the LLM.  Layout:
            persona instructions
            target preamble
            longterm + project banks (full inclusion, user-curated)
            top-K coder.db rows by tag-bitmap overlap
            goal
            previous draft (if any)
            previous compile output (if any)
            closing instruction
        """
        lines: List[str] = []
        lines.append(
            "You are a C code generator running inside a 64 KB office "
            "app.  Output ONLY a complete C program inside a fenced "
            "code block (```c ... ```).  No commentary outside the "
            "fence.  The program must compile with cc on Linux x86_64.\n")
        if self.s.target == 1:
            lines.append("Target: clean.  cc -Wall -Wextra must produce "
                         "zero warnings as well as zero errors.\n")
        elif self.s.target == 2:
            lines.append("Target: perfect.  cc -Wall -Wextra clean AND "
                         "the compiled program must run without crashing "
                         "or printing diagnostics.\n")
        else:
            lines.append("Target: good-enough.  cc must compile.\n")
        # Banks: longterm + project.  Recent comes from the DB instead
        # so we get tag-bitmap-ranked retrieval rather than raw text.
        for b in (BANK_LONGTERM, BANK_PROJECT):
            text = self.banks.text[b]
            if text:
                lines.append(f"[{BANK_LABELS[b]} bank]\n"
                             f"{_safe_decode(text)}\n")
        # Top-K rows from coder.db by tag-bitmap overlap with goal+err.
        q = TinyDB.tag_bitmap(self.s.goal) | TinyDB.tag_bitmap(self.s.err)
        scored: List[Tuple[int, TdbRow]] = []
        for i in range(self.db.count()):
            r = self.db.read(i)
            if r is None:
                continue
            s = bin(q & r.tag_bitmap).count("1")
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda sr: -sr[0])
        if scored:
            lines.append("[recent (top-K from coder.db)]")
            for _, r in scored[:4]:
                lines.append(f"  · {_safe_decode(r.body)}")
            lines.append("")
        # Goal
        lines.append("[goal]\n" +
                     (_safe_decode(self.s.goal) if self.s.goal
                      else "(no goal entered)") + "\n")
        # Previous draft
        if self.s.draft:
            lines.append("[previous attempt]\n```c\n" +
                         _safe_decode(self.s.draft) + "\n```\n")
        # Previous compile output
        if self.s.err:
            lines.append("[compile output]\n" +
                         _safe_decode(self.s.err) + "\n")
        lines.append("Now produce the next draft.  Address any errors "
                     "above and respect the target.")
        return "\n".join(lines)

    @staticmethod
    def extract_code(text: str) -> bytes:
        """Find the largest ```c ... ``` block in the LLM response.  If
        no fence is present, return the whole response (the C version
        does the same fallback so a model that forgets the fence isn't
        a wasted iteration)."""
        best: Tuple[int, int] = (-1, -1)
        i = 0
        while True:
            j = text.find("```", i)
            if j < 0:
                break
            nl = text.find("\n", j + 3)
            if nl < 0:
                break
            start = nl + 1
            close = text.find("```", start)
            end = close if close >= 0 else len(text)
            if end - start > best[1] - best[0]:
                best = (start, end)
            i = end + 3 if close >= 0 else len(text)
        if best[0] < 0:
            return text.encode("utf-8")
        return text[best[0]:best[1]].encode("utf-8")

    # ── one iteration with retry-on-empty-key ─────────────────────
    def iterate(self) -> int:
        """One round-trip: build prompt, call LLM, extract code, write
        source, compile, (run if target=perfect).  Returns 0 = target
        met, 1 = failed.  On compile/run failure the caller is expected
        to call log_recent() to record the failure for the agent's
        own context retrieval next time."""
        prompt = self.build_prompt()
        content: Optional[str] = None
        fail = "(curl failed — check ask config)"
        succeeded_after_retry = False
        for attempt in range(CODER_RETRY_MAX):
            if attempt > 0:
                _print_status(
                    f"coder: provider rejected — fresh key "
                    f"(try {attempt + 1}/{CODER_RETRY_MAX})")
                self.ask.fetch_random_key()
                succeeded_after_retry = True
            self.ask.reset()
            self.ask.msg_add(0, prompt.encode("utf-8"))
            self.banks.load(BANK_PERSONALITY)
            raw = self.ask.call()
            if raw is None:
                fail = "(curl failed)"
                continue
            if not raw:
                fail = "(empty response — likely 429 / rate-limited)"
                continue
            content = self.ask.extract_content(raw)
            if content is None:
                fail = "(no 'content' or 'text' field — provider error?)"
                continue
            if succeeded_after_retry:
                self.ask.save_conf()
            break
        if content is None:
            self.s.err = (f"{fail} (after {CODER_RETRY_MAX} retries)"
                          ).encode("utf-8")
            return 1
        # Extract the code, write to disk, compile.
        self.s.draft = self.extract_code(content)[:CODER_DRAFT_CAP]
        self.tmp_src.write_bytes(self.s.draft)
        rc = self.compile(strict=self.s.target >= 1)
        try:
            self.s.err = self.tmp_err.read_bytes()[:CODER_ERR_CAP]
        except OSError:
            self.s.err = b""
        if rc != 0:
            return 1
        if self.s.target == 0:
            return 0
        if self.s.target == 1:
            # warnings show as non-empty err even on rc=0
            return 1 if self.s.err else 0
        # target=perfect: also run.
        if self.runtest() != 0:
            try:
                self.s.err = self.tmp_run.read_bytes()[:CODER_ERR_CAP]
            except OSError:
                pass
            return 1
        return 0

    # ── recent-bank + DB logging ──────────────────────────────────
    def log_recent(self) -> None:
        """Append the (iter, goal, error) trio to BANK_RECENT (FIFO line
        eviction) AND insert a tagged row into coder.db.  Two paths
        because the bank is for human reading and the DB is for the
        agent's own tag-bitmap retrieval after the bank rolls over."""
        rec = (b"--- iter " + str(self.s.iter).encode() +
               f" (target={CODER_TARGET_NAMES[self.s.target]})\n".encode() +
               b"goal: "  + self.s.goal[:96] + b"\n" +
               b"error: " + self.s.err[:320] + b"\n")
        self.banks.append(BANK_RECENT, rec)
        row = TdbRow(
            bank=BANK_RECENT,
            timestamp=int(time.time()),
            tag_bitmap=(TinyDB.tag_bitmap(self.s.goal)
                        | TinyDB.tag_bitmap(self.s.err)),
            body=rec[:TDB_BODY_SIZE],
        )
        self.db.insert(row)

    # ── project workflow: push + compose + mission ────────────────
    def proj_count_steps(self) -> int:
        if not CODER_PROJ_FILE.exists():
            return 0
        return CODER_PROJ_FILE.read_bytes().count(b"\n[step ") + (
            1 if CODER_PROJ_FILE.read_bytes().startswith(b"[step ") else 0)

    def proj_push(self) -> int:
        """Append the current /tmp/coder_attempt.c as a `[step NN]` block
        to coder_project.txt, mirror a one-line summary into the project
        bank.  Returns the step number on success, 0 if the source
        binary doesn't exist, -1 if the project file is at the reserve
        threshold (60 KB)."""
        if not self.tmp_src.exists():
            return 0
        src = self.tmp_src.read_bytes()
        existing = b""
        if CODER_PROJ_FILE.exists():
            existing = CODER_PROJ_FILE.read_bytes()
            if len(existing) >= CODER_PROJ_MAX - CODER_PROJ_RESERVE:
                return -1
        step = self.proj_count_steps() + 1
        header = f"[step {step:02d}] ".encode() + self.s.goal + b"\n"
        block  = header + b"@@@\n" + src
        if not block.endswith(b"\n"):
            block += b"\n"
        block += b"@@@\n"
        CODER_PROJ_FILE.write_bytes(existing + block)
        # mirror summary into project bank for next iterate()
        self.banks.load(BANK_PROJECT)
        line = f"step {step:02d}: ".encode() + self.s.goal + b"\n"
        self.banks.append(BANK_PROJECT, line)
        self.banks.save(BANK_PROJECT)
        return step

    def compose(self) -> int:
        """Re-prompt the LLM with the project bank + every saved
        snippet, ask for a single merged C program.  Result lands in
        /tmp/coder_attempt.c + compiled.

        Return values match C: 0 = clean compile, 1 = compile-with-
        warnings, -1 = no snippets, -2 = LLM call failed, -3 = prompt
        too big for free-tier cap.
        """
        if not CODER_PROJ_FILE.exists():
            return -1
        snippets = CODER_PROJ_FILE.read_bytes()
        if not snippets:
            return -1
        self.banks.load(BANK_PROJECT)
        prompt = (
            "You are a C code merger.  Below is a project plan and a "
            "sequence of working C programs (each delimited by @@@).  "
            "Combine them into a SINGLE C program that preserves ALL "
            "features from each step and compiles cleanly with `cc -O2 "
            "-o out file.c`.  Return ONLY the merged C source, wrapped "
            "in ```c ... ``` if you must.\n\n"
            "[project plan]\n"
            + _safe_decode(self.banks.text[BANK_PROJECT])
            + "\n\n[snippets]\n"
            + _safe_decode(snippets) + "\n")
        if len(prompt.encode("utf-8")) > CODER_COMPOSE_WARN_BYTES:
            self.s.err = (
                f"compose aborted — prompt is {len(prompt)} B "
                f"(>{CODER_COMPOSE_WARN_BYTES} B free-tier cap).\n"
                f"  trim {CODER_PROJ_FILE} or use a Gemini-direct key."
            ).encode("utf-8")
            return -3
        self.ask.reset()
        self.ask.msg_add(0, prompt.encode("utf-8"))
        self.banks.load(BANK_PERSONALITY)
        content, fail = self.ask.send_retrying()
        if content is None:
            self.s.err = f"compose failed: {fail}".encode("utf-8")
            return -2
        self.s.draft = self.extract_code(content)[:CODER_DRAFT_CAP]
        self.tmp_src.write_bytes(self.s.draft)
        rc = self.compile(strict=False)
        try:
            self.s.err = self.tmp_err.read_bytes()[:CODER_ERR_CAP]
        except OSError:
            self.s.err = b""
        return 0 if rc == 0 else 1

    def breakdown(self, goal: bytes) -> List[str]:
        """Ask the LLM to break `goal` into 3-5 sequential C-program
        subtasks.  Each subtask must be self-contained and mergeable.
        Returns the parsed list (empty on parse failure)."""
        prompt = (
            f"You are a project planner.  Break the following overarching "
            f"goal into between 3 and {MISSION_MAX_SUBTASKS} sequential "
            f"C-program subtasks.  Each subtask MUST be implementable as "
            f"a self-contained C program with main() and printf-style "
            f"output that compiles cleanly with `cc file.c`, and that "
            f"can later be merged with the others.  Reply with ONLY a "
            f"numbered list, one subtask per line, in the form "
            f"`1. subtask description`.  No code, no preamble, no "
            f"postscript.\n\nGoal: {_safe_decode(goal)}\n")
        self.ask.reset()
        self.ask.msg_add(0, prompt.encode("utf-8"))
        self.banks.load(BANK_PERSONALITY)
        content, _ = self.ask.send_retrying()
        if content is None:
            return []
        out: List[str] = []
        for line in content.splitlines():
            m = re.match(r"\s*\d+[.\)]\s*(.+?)\s*$", line)
            if m:
                out.append(m.group(1)[:CODER_GOAL_CAP - 1])
            if len(out) >= MISSION_MAX_SUBTASKS:
                break
        return out

    def mission(self) -> None:
        """Plan→iterate→push→compose loop.  Take the current goal,
        decompose it into subtasks, run each through coder.iterate() up
        to MISSION_PER_STEP_MAX times, push successes into the project
        file, then call compose() to merge everything into one program.
        At the cap this is dozens of LLM calls and can take many
        minutes — there's no mid-mission cancel."""
        original_goal = self.s.goal
        _print_status("mission: planning subtasks…")
        subtasks = self.breakdown(original_goal)
        if not subtasks:
            _print_status("mission: planner returned no subtasks")
            return
        successes = 0
        for s_i, subtask in enumerate(subtasks, 1):
            self.s.goal = subtask.encode("utf-8")[:CODER_GOAL_CAP - 1]
            _print_status(
                f"mission {s_i}/{len(subtasks)}: {subtask[:60]}")
            rc = 1
            for _ in range(MISSION_PER_STEP_MAX):
                self.s.iter += 1
                rc = self.iterate()
                if rc == 0:
                    break
            if rc == 0:
                self.proj_push()
                successes += 1
        if successes == 0:
            _print_status("mission: every subtask failed")
            return
        self.s.goal = original_goal
        _print_status("mission: composing merged program…")
        comp_rc = self.compose()
        exit_code = self.runtest() if comp_rc >= 0 and self.tmp_bin.exists() \
                                   else -1
        suffix = {0: "merged clean", 1: "merged with warnings",
                  -2: "compose failed", -3: "prompt too big to merge"
                  }.get(comp_rc, "no merge")
        _print_status(
            f"mission done: {successes}/{len(subtasks)} subtasks · "
            f"{suffix}" + (f" · run exit={exit_code}"
                           if exit_code >= 0 else ""))


# ──────────────────────────────────────────────────────────────────
# REPL — replaces the C TUI.  Same semantics as the C `ask` and
# `coder` apps but driven by a stdin-based menu instead of hotkeys.
# ──────────────────────────────────────────────────────────────────

def _print_status(msg: str) -> None:
    """One-line status print.  Goes to stderr so it doesn't pollute the
    coder/ask REPL output stream."""
    print(msg, file=sys.stderr, flush=True)


def run_ask() -> int:
    """Line-oriented chat REPL.  Commands: /quit, /new, /sync, /settings,
    /history.  Anything else is a chat message."""
    banks = BankStore()
    banks.load_all()
    ask = AskClient(banks)
    ask.load_conf()
    print(f"tinyagent · ask ({ask.provider()} → {ask.model})")
    if not ask.api_key:
        print("(no api_key — type /settings to enter one or "
              "/sync to fetch a free-tier key)")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/q"):
            return 0
        if line == "/new":
            ask.reset()
            print("(history cleared)")
            continue
        if line == "/history":
            for m in ask.messages:
                if m.hidden:
                    continue
                tag = "ai" if m.role else "you"
                print(f"  {tag}> {_safe_decode(m.text)}")
            continue
        if line == "/sync":
            ask.fetch_random_key()
            ask.save_conf()
            print(f"(picked key, model now {ask.model}, "
                  f"endpoint {ask.endpoint})")
            continue
        if line.startswith("/settings"):
            print(f"  api_key  = {'(set)' if ask.api_key else '(unset)'}")
            print(f"  endpoint = {ask.endpoint}")
            print(f"  model    = {ask.model}")
            print("  edit by setting environment vars TINYAGENT_KEY / "
                  "TINYAGENT_ENDPOINT / TINYAGENT_MODEL and re-run, "
                  "or hand-edit tinyagent.conf in cwd.")
            continue
        ask.hist_push(line.encode("utf-8"))
        ask.msg_add(0, line.encode("utf-8"))
        if not ask.api_key:
            print("(no api_key — type /settings or /sync first)")
            ask.messages.pop()
            continue
        content, fail = ask.send_retrying()
        if content is None:
            print(f"(error: {fail})")
            continue
        ask.msg_add(1, content.encode("utf-8"))
        print(f"ai> {content}")


def run_coder() -> int:
    """Line-oriented coder REPL.  Hotkeys mapped to slash-commands:

        e/<text>   set the goal
        ENTER      one iteration
        a          auto: up to CODER_MAX_ITERS iterations
        m          mission: decompose + iterate + compose
        p          push current /tmp/coder_attempt.c into the project
        c          compose merged program from project
        x          execute /tmp/coder_attempt
        t          cycle target (good_enough → clean → perfect)
        1..4       edit memory bank N
        r          log current (goal,err) into recent bank + coder.db
        s          save state
        q          quit
        /show      print current goal + draft + err
    """
    banks = BankStore()
    banks.load_all()
    db = TinyDB()
    db.open()
    ask = AskClient(banks)
    ask.load_conf()
    coder = CoderAgent(ask, banks, db)
    # Restore previously-saved state if any.
    if CODER_STATE_PATH.exists():
        try:
            data = CODER_STATE_PATH.read_bytes()
            if len(data) >= 4:
                coder.s.target = data[0] & 3
                gn = data[1] | (data[2] << 8)
                coder.s.goal = data[4:4 + gn][:CODER_GOAL_CAP - 1]
        except OSError:
            pass
    print("tinyagent · coder")
    print("  ENTER iterate, a auto, m mission, p push, c compose, "
          "x exec, t target,")
    print("  e <goal> set goal, 1..4 edit bank, r log recent, "
          "s save, q quit, /show")
    try:
        while True:
            print(f"  [target={CODER_TARGET_NAMES[coder.s.target]} "
                  f"iter={coder.s.iter} "
                  f"goal={(coder.s.goal[:40] + b'...' if len(coder.s.goal) > 40 else coder.s.goal).decode('utf-8', 'replace')}]")
            try:
                line = input("coder> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if line in ("q", "/q", "/quit"):
                break
            if line.startswith("e ") or line == "e":
                coder.s.goal = line[2:].encode("utf-8")[:CODER_GOAL_CAP - 1]
                continue
            if line in ("t", "/target"):
                coder.s.target = (coder.s.target + 1) % 3
                continue
            if line in ("1", "2", "3", "4"):
                _edit_bank(banks, int(line) - 1)
                continue
            if line == "r":
                coder.log_recent()
                banks.save(BANK_RECENT)
                continue
            if line == "p":
                step = coder.proj_push()
                if step == -1:
                    print("(push failed — coder_project.txt is full)")
                elif step == 0:
                    print("(push failed — no /tmp/coder_attempt.c?)")
                else:
                    print(f"(pushed step {step:02d})")
                continue
            if line == "c":
                if not ask.api_key:
                    print("(no api_key — set one with /sync in ask)")
                    continue
                rc = coder.compose()
                msg = {0: "✓ composed merged program (cc clean)",
                       -1: "(no snippets — push first)",
                       -2: "(LLM call failed — see err)",
                       -3: "(prompt too large — see err)"}.get(
                            rc, "(composed but cc had issues)")
                print(msg)
                continue
            if line == "m":
                if not coder.s.goal:
                    print("(no goal — type 'e <text>' first)")
                    continue
                if not ask.api_key:
                    print("(no api_key — set one with /sync in ask)")
                    continue
                coder.mission()
                continue
            if line == "x":
                if not coder.tmp_bin.exists():
                    print("(no binary — type ENTER to build first)")
                    continue
                rc = coder.runtest()
                try:
                    out = coder.tmp_run.read_text()
                except OSError:
                    out = "(no output captured)"
                print(out, end="")
                if not out.endswith("\n"):
                    print()
                print(f"(exit={rc})")
                continue
            if line == "s":
                gn = len(coder.s.goal)
                hdr = bytes([coder.s.target & 3, gn & 0xFF,
                             (gn >> 8) & 0xFF, 0])
                CODER_STATE_PATH.write_bytes(hdr + coder.s.goal)
                print("(state saved)")
                continue
            if line == "/show":
                print(f"goal:  {_safe_decode(coder.s.goal)}")
                print(f"draft (last 800 B): "
                      f"{_safe_decode(coder.s.draft[-800:])}")
                print(f"err   (last 800 B): "
                      f"{_safe_decode(coder.s.err[-800:])}")
                continue
            if line == "a":
                if not coder.s.goal:
                    print("(no goal — type 'e <text>' first)")
                    continue
                local = 0
                while local < CODER_MAX_ITERS:
                    coder.s.iter += 1
                    local += 1
                    print(f"(auto iter {local}…)")
                    rc = coder.iterate()
                    if rc == 0:
                        print("(✓ target met)")
                        break
                    coder.log_recent()
                    print("(× failed — see err)")
                else:
                    print("(auto: gave up after max iters)")
                continue
            if line == "" or line == "/iter":
                if not coder.s.goal:
                    print("(no goal — type 'e <text>' first)")
                    continue
                coder.s.iter += 1
                print("(calling LLM…)")
                rc = coder.iterate()
                if rc != 0:
                    coder.log_recent()
                print("(✓ target met)" if rc == 0
                      else "(× failed — type /show for err)")
                continue
            print(f"(unknown command: {line!r})")
    finally:
        for b in range(BANK_COUNT):
            banks.save(b)
        db.close()
    return 0


def _edit_bank(banks: BankStore, b: int) -> None:
    """Open the bank file in $EDITOR (or vi) and reload after exit.
    Replaces the C in-app notepad — we trust the user's existing
    editor instead of building one."""
    path = Path(BANK_FILES[b])
    path.touch()
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(path)], check=False)
    # Truncate to BANK_BYTES-1 the same way C bank reload caps it.
    raw = path.read_bytes()
    if len(raw) > BANK_BYTES - 1:
        path.write_bytes(raw[:BANK_BYTES - 1])
    banks.load(b)
    print(f"(reloaded {BANK_LABELS[b]} bank, {len(banks.text[b])} B)")


# ──────────────────────────────────────────────────────────────────
# Dispatch.  C: main_c — single argv check for "ask"/"coder",
# default to coder.
# ──────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 2:
        sub = argv[1]
        if sub in ("ask",):    return run_ask()
        if sub in ("coder",):  return run_coder()
        if sub in ("-h", "--help"):
            print(__doc__)
            return 0
    return run_coder()


if __name__ == "__main__":
    sys.exit(main())

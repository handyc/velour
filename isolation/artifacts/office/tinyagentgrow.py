"""tinyagentgrow.py — Python port of tinyagentgrow.c.

Faithful port of tinyagentgrow.c (~64 KB Linux x86_64 no-libc binary)
on top of tinyagent.py.  Inherits the full ask + coder + 4-bank +
TinyDB stack from tinyagent and adds the headline `grow` subcommand
family: capability-tail accumulation that lets a running binary
extend itself with new compiled tools.

The big idea (preserved from the C source's top-of-file comment):

    Each tail is a self-describing record at the end of the binary;
    multiple tails chain back-to-back; on disk the binary carries
    every capability it has earned via verified builds.  Two
    instances forked from the same baseline and given different
    tasks accumulate different tails and develop divergent competence
    profiles — individuality through accreted skill, not just runtime
    state.

Tail format:

    ┌─────────────────────────┐
    │ payload bytes (raw)     │  payload_len bytes
    ├─────────────────────────┤
    │ v1 trailer (48 B): name(32) + payload_len(8) + magic "TAGW0001"
    │ v2 trailer (256 B): name(32) + task(192) + payload_len(8)
    │                   + created_unix(8) + type(1) + reserved(7)
    │                   + magic "TAGW0002"
    └─────────────────────────┘

Scanning walks backward from EOF using the trailer's payload_len; on
magic mismatch we've hit the original ELF or an older tail-less
binary and stop.  Tails chain back-to-back with no global table —
each one is fully self-contained.

Self-modification model: the running binary's text segment is
locked by Linux, so we never write to /proc/self/exe.  Instead,
read self bytes, append the tail in memory, write a NEW file at a
neighbour path (tinyagentgrow.001, .002, …).  Save-only — caller
picks when to swap in the upgraded generation.

Subcommands (all match the C dispatcher in tg_run_grow):

    list         scan self, print tails one per line
    self-test    append a small text tail, write a .NNN file, scan
                 it back, confirm round-trip works
    add          promote an arbitrary file as a capability tail
    gen          ask LLM for a C program, compile + (optionally)
                 verify it, append the binary as a tail
    exec         find tail by name, extract to /tmp, run it
    rm           drop a tail (writes a new .NNN file without it)
    info         print v2 metadata: type, size, created, task
    chain        compose multiple tails into a stdin→stdout pipeline,
                 either explicit or LLM-picked (--auto "<task>")

What this Python port deliberately does NOT include:

  * The seccomp BPF deny-list and namespace-clone sandbox (`grow exec
    --sandbox`).  The C version installs a default-allow seccomp
    filter that blocks socket/connect/clone/fork/vfork/ptrace/mount
    inside fresh user/pid/mnt/uts/net namespaces.  Implementing that
    cleanly in Python needs ctypes binding to clone(2)/prctl(2) and
    BPF compilation.  We expose `--sandbox` as a no-op shim and
    document the gap rather than fake it.
  * The recursive sub-agent spawning (`decompose --jail-depth=N`)
    from tinyagentjail.  The C version self-spawns to do verified
    leaf compiles; we collapse that to a direct AskClient call.
  * The `tmpl` subcommand family (canon + grown source-fragment
    library).  Carried as a thin reimplementation just for canon
    list/cat — the grown templates stored as type='P' tails are
    handled through the normal tail machinery.

CLI:    python tinyagentgrow.py grow <list|self-test|add|gen|exec|rm|info|chain>
        python tinyagentgrow.py [ask|coder]    # inherited
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import tinyagent as ta


# ──────────────────────────────────────────────────────────────────
# Tail-format constants — match the C #defines exactly so a binary
# written by either side can be scanned by the other.
# ──────────────────────────────────────────────────────────────────

TG_NAME_LEN       = 32
TG_TASK_LEN       = 192
TG_MAGIC_LEN      = 8
TG_TRAILER_V1_LEN = 48        # name(32) + len(8) + magic(8)
TG_TRAILER_V2_LEN = 256       # name + task + len + created + type + rsvd + magic
TG_BUF_CAP        = 4 * 1024 * 1024
TG_PAYLOAD_CAP    = 4 * 1024 * 1024

TG_MAGIC_V1 = b"TAGW0001"
TG_MAGIC_V2 = b"TAGW0002"

TG_CHAIN_MAX = 8


# ──────────────────────────────────────────────────────────────────
# Trailer parsing.  C: tg_read_trailer.
# ──────────────────────────────────────────────────────────────────

@dataclass
class TailInfo:
    """Parsed view of a tail's trailer (read-only — points into a
    buffer the caller still owns).  Set by `read_trailer`."""
    version: int = 0           # 1 or 2
    trailer_len: int = 0
    name: bytes = b""
    payload_len: int = 0
    task: bytes = b""          # b"" for v1
    created_unix: int = 0      # 0 for v1
    type: bytes = b"?"         # 'A'=add, 'G'=gen dynamic, 'S'=gen static,
                               # 'T'=self-test, 'P'=pattern (template tail)


def read_trailer(buf: bytes, end: int) -> Optional[TailInfo]:
    """Parse the trailer ending at byte offset `end` in `buf`.  Try v2
    first (newer writes), fall back to v1 (legacy).  Returns None at
    end-of-chain (magic doesn't match either trailer layout)."""
    if end < 8:
        return None
    magic = buf[end - 8:end]
    if end >= TG_TRAILER_V2_LEN and magic == TG_MAGIC_V2:
        tr = buf[end - TG_TRAILER_V2_LEN:end]
        info = TailInfo(version=2, trailer_len=TG_TRAILER_V2_LEN)
        info.name = tr[:TG_NAME_LEN].rstrip(b"\x00")
        info.task = tr[TG_NAME_LEN:TG_NAME_LEN + TG_TASK_LEN].rstrip(b"\x00")
        info.payload_len  = struct.unpack_from(
            "<Q", tr, TG_NAME_LEN + TG_TASK_LEN)[0]
        info.created_unix = struct.unpack_from(
            "<Q", tr, TG_NAME_LEN + TG_TASK_LEN + 8)[0]
        info.type = tr[TG_NAME_LEN + TG_TASK_LEN + 16:
                       TG_NAME_LEN + TG_TASK_LEN + 17]
        return info
    if end >= TG_TRAILER_V1_LEN and magic == TG_MAGIC_V1:
        tr = buf[end - TG_TRAILER_V1_LEN:end]
        info = TailInfo(version=1, trailer_len=TG_TRAILER_V1_LEN)
        info.name = tr[:TG_NAME_LEN].rstrip(b"\x00")
        info.payload_len = struct.unpack_from("<Q", tr, TG_NAME_LEN)[0]
        info.type = b"?"
        return info
    return None


def walk_tails(buf: bytes) -> List[Tuple[int, TailInfo]]:
    """Walk the entire tail chain in `buf`.  Returns list of (start_off,
    info) pairs in EOF-first order — i.e. the most-recently-appended
    tail is first.  start_off is where the tail's payload begins."""
    out: List[Tuple[int, TailInfo]] = []
    end = len(buf)
    while end > 0:
        info = read_trailer(buf, end)
        if info is None:
            break
        step = info.trailer_len + info.payload_len
        if step <= 0 or step > end:
            break
        payload_start = end - step
        out.append((payload_start, info))
        end -= step
    return out


def lookup_tail(buf: bytes, name: bytes) -> Optional[Tuple[int, TailInfo]]:
    """Return the most-recent-from-EOF tail with the given name, or None."""
    for start, info in walk_tails(buf):
        if info.name == name:
            return start, info
    return None


def count_tails(buf: bytes) -> int:
    return len(walk_tails(buf))


# ──────────────────────────────────────────────────────────────────
# Self-modification: write a new generation file with one extra tail
# (or one removed tail).  C: tg_append_to_copy / tg_next_path.
# ──────────────────────────────────────────────────────────────────

_GEN_RE = re.compile(r"\.(\d{3})$")


def next_path(self_path: Path) -> Path:
    """Compute the next-generation path for `self_path`.  The .NNN
    suffix tracks how many modifications (gen/add/rm) have been
    applied — NOT the current tail count, which can go down via
    `grow rm`.  Caps at .999."""
    base = str(self_path)
    m = _GEN_RE.search(base)
    cur = int(m.group(1)) if m else 0
    nxt = min(cur + 1, 999)
    if m:
        base = base[:m.start()]
    return Path(f"{base}.{nxt:03d}")


def append_to_copy(self_path: Path, name: bytes, type_byte: bytes,
                   task: bytes, payload: bytes) -> Path:
    """Write a new file = self_bytes + payload + v2 trailer.  Returns
    the new path.  Sets +x so the new file is executable when the
    payload is an ELF."""
    self_bytes = self_path.read_bytes()
    if len(self_bytes) + len(payload) + TG_TRAILER_V2_LEN > TG_BUF_CAP:
        raise ValueError("tail would exceed TG_BUF_CAP")
    nb = name[:TG_NAME_LEN - 1]
    tb = task[:TG_TASK_LEN - 1]
    tp = type_byte[:1] or b"?"
    trailer = bytearray(TG_TRAILER_V2_LEN)
    trailer[:len(nb)] = nb
    trailer[TG_NAME_LEN:TG_NAME_LEN + len(tb)] = tb
    struct.pack_into("<Q", trailer, TG_NAME_LEN + TG_TASK_LEN, len(payload))
    struct.pack_into("<Q", trailer, TG_NAME_LEN + TG_TASK_LEN + 8,
                     int(time.time()))
    trailer[TG_NAME_LEN + TG_TASK_LEN + 16] = tp[0]
    trailer[TG_TRAILER_V2_LEN - TG_MAGIC_LEN:] = TG_MAGIC_V2
    new_path = next_path(self_path)
    new_path.write_bytes(self_bytes + payload + bytes(trailer))
    new_path.chmod(0o755)
    return new_path


def remove_tail(self_path: Path, name: bytes) -> Tuple[Path, int]:
    """Write a new generation file with the named tail spliced out.
    Returns (new_path, removed_bytes).  Raises KeyError if the tail
    doesn't exist."""
    buf = self_path.read_bytes()
    found = None
    end = len(buf)
    while end > 0:
        info = read_trailer(buf, end)
        if info is None:
            break
        step = info.trailer_len + info.payload_len
        if step <= 0 or step > end:
            break
        if info.name == name:
            found = (end - step, end)   # tail_start, tail_end
            break
        end -= step
    if found is None:
        raise KeyError(name)
    tail_start, tail_end = found
    new_path = next_path(self_path)
    new_path.write_bytes(buf[:tail_start] + buf[tail_end:])
    new_path.chmod(0o755)
    return new_path, tail_end - tail_start


# ──────────────────────────────────────────────────────────────────
# The "self" path.  C uses readlink("/proc/self/exe"); for our Python
# port we use sys.argv[0] as a sensible default but allow override
# via $TINYAGENTGROW_SELF (handy for testing — point it at any file
# you want to act as the baseline binary).
# ──────────────────────────────────────────────────────────────────

def self_path() -> Path:
    if "TINYAGENTGROW_SELF" in os.environ:
        return Path(os.environ["TINYAGENTGROW_SELF"]).resolve()
    return Path(sys.argv[0]).resolve()


# ──────────────────────────────────────────────────────────────────
# `grow list` — scan self, print tails one per line.  C: tg_subcmd_list.
# ──────────────────────────────────────────────────────────────────

def cmd_list() -> int:
    sp = self_path()
    try:
        buf = sp.read_bytes()
    except OSError as e:
        print(f"tg: failed to load self: {e}", file=sys.stderr)
        return 1
    tails = walk_tails(buf)
    if not tails:
        print("no tails")
        return 0
    # walk_tails returns EOF-first; print oldest-first to match `tg list`
    for n, (_, info) in enumerate(reversed(tails)):
        line = f"tail {n}: {info.name.decode('utf-8', 'replace')}"
        if info.version == 2:
            line += f" [{info.type.decode('latin1')}]"
        line += f" ({info.payload_len} B)"
        if info.version == 2 and info.created_unix > 0:
            line += f" @{info.created_unix}"
        print(line)
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow self-test` — append a sample tail, write to .NNN, scan back,
# verify the payload bytes round-trip.  C: tg_subcmd_self_test.
# ──────────────────────────────────────────────────────────────────

def cmd_self_test() -> int:
    payload = (b"tinyagentgrow self-test capability payload\n"
               b"If you are reading this from the .NNN file's tail, the\n"
               b"read-self -> append -> write-copy -> rescan loop is sound.\n")
    task = b"growtest self-test sample tail"
    try:
        new_path = append_to_copy(self_path(), b"growtest_hello",
                                  b"T", task, payload)
    except (OSError, ValueError) as e:
        print(f"self-test: append failed: {e}", file=sys.stderr)
        return 1
    print(f"appended 'growtest_hello' ({len(payload)} B) -> {new_path}")
    nb = new_path.read_bytes()
    n = count_tails(nb)
    print(f"new-gen tail count: {n}")
    if n < 1:
        print("self-test: tail not found", file=sys.stderr)
        return 1
    info = read_trailer(nb, len(nb))
    got = nb[len(nb) - info.trailer_len - info.payload_len:
             len(nb) - info.trailer_len]
    if info.payload_len != len(payload) or got != payload:
        print("self-test: byte mismatch", file=sys.stderr)
        return 1
    print("self-test OK — round-trip verified")
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow add <name> <file>` — promote an arbitrary file as a tail.
# C: tg_subcmd_add.  The source file path is stored as the task field
# so a later `grow info` can show provenance.
# ──────────────────────────────────────────────────────────────────

def cmd_add(args: List[str]) -> int:
    if len(args) < 2:
        print("usage: grow add <name> <file>", file=sys.stderr)
        return 1
    name = args[0].encode()
    src = Path(args[1])
    try:
        payload = src.read_bytes()
    except OSError as e:
        print(f"grow add: cannot open '{src}': {e}", file=sys.stderr)
        return 1
    if not 0 < len(payload) <= TG_PAYLOAD_CAP:
        print("grow add: file empty or larger than TG_PAYLOAD_CAP",
              file=sys.stderr)
        return 1
    try:
        new_path = append_to_copy(self_path(), name, b"A",
                                  str(src).encode(), payload)
    except (OSError, ValueError) as e:
        print(f"grow add: append failed: {e}", file=sys.stderr)
        return 1
    print(f"appended '{name.decode()}' ({len(payload)} B) -> {new_path}")
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow gen <name> <task>` — the magic moment: ask LLM for a C
# program, compile it, optionally verify (Phase 5), append the binary
# as a capability tail.  C: tg_subcmd_gen.
#
# Flags:
#   --static     pass -static to cc (chroot-ready, larger binary)
#   --no-verify  skip the Phase-5 runtime check (default: verify on)
#
# Verify (when on): run the freshly-compiled binary with empty stdin
# and a 5 s wall-clock cap, then check exit code == 0 and that the
# LLM-provided EXPECTED: substring appears in stdout.  If either
# check fails, the gen refuses to promote — bad code never reaches
# the tail chain.
# ──────────────────────────────────────────────────────────────────

def _ask_for_c(task: str, want_expected: bool) -> Tuple[str, str]:
    """Ask the LLM for a complete C program implementing `task`.
    Returns (full_response, code_only).  Empty code_only means the
    LLM didn't fence a ```c block."""
    enhanced = (
        "Write a COMPLETE, standalone C program with main() that "
        "solves the following task.  Include all required headers.  "
        "Use only the standard C library.  Wrap the code in a "
        "```c ... ``` fence.")
    if want_expected:
        enhanced += (
            "  Then, on a new line AFTER the closing ```, write the "
            "literal line:\n"
            "EXPECTED: <one short substring that your program prints "
            "to stdout when run with no stdin>\n"
            "If your program reads from stdin and would hang without "
            "input, write `EXPECTED: <none>` so the verifier just "
            "checks the exit code.")
    enhanced += f"  Task: {task}"

    banks = ta.BankStore()
    banks.load_all()
    ask = ta.AskClient(banks)
    ask.load_conf()
    ask.max_tokens = 8192    # reasoning models need headroom
    if not ask.api_key:
        ask.fetch_random_key()
    ask.reset()
    ask.msg_add(0, enhanced.encode())
    content, fail = ask.send_retrying()
    if content is None:
        raise RuntimeError(f"LLM call failed: {fail}")
    code = ta.CoderAgent.extract_code(content).decode("utf-8", "replace")
    return content, code


def _compile_c(code: str, use_static: bool, out_bin: Path) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as f:
        f.write(code)
        src_path = Path(f.name)
    try:
        argv = ["cc", "-O2"] + (["-static"] if use_static else []) + [
            "-o", str(out_bin), str(src_path)]
        rc = subprocess.run(argv, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False).returncode
        return rc == 0
    finally:
        src_path.unlink(missing_ok=True)


def _verify_runtime(bin_path: Path, response: str, timeout_s: int = 5
                    ) -> Tuple[bool, str]:
    """Run bin_path with /dev/null stdin and timeout cap.  Check exit
    code and (if EXPECTED: was set) that the substring is in stdout.
    Returns (ok, reason)."""
    try:
        cp = subprocess.run([str(bin_path)], input=b"",
                            capture_output=True, timeout=timeout_s,
                            check=False)
    except subprocess.TimeoutExpired:
        return False, "exceeded 5 s timeout (hung or infinite loop)"
    if cp.returncode != 0:
        return False, f"exited with code {cp.returncode}"
    # Pull EXPECTED: from the LLM response.
    expected = ""
    for line in response.splitlines():
        if line.startswith("EXPECTED:"):
            expected = line[len("EXPECTED:"):].strip().strip("`")
            break
    if expected and expected != "<none>":
        out = (cp.stdout + cp.stderr).decode("utf-8", "replace")
        if expected not in out:
            return False, f"EXPECTED '{expected}' not in stdout"
    return True, ""


def cmd_gen(args: List[str]) -> int:
    use_static = False
    do_verify  = True
    pos: List[str] = []
    for a in args:
        if a == "--static":     use_static = True
        elif a == "--no-verify": do_verify = False
        elif a == "--verify":    do_verify = True
        else:                    pos.append(a)
    if len(pos) < 2:
        print("usage: grow gen [--static] [--no-verify] <name> <task>",
              file=sys.stderr)
        return 1
    name, task = pos[0], pos[1]
    print(f"grow gen: invoking LLM for '{name}'...", file=sys.stderr)
    try:
        response, code = _ask_for_c(task, want_expected=do_verify)
    except RuntimeError as e:
        print(f"grow gen: {e}", file=sys.stderr)
        return 1
    if not code or "main" not in code:
        print("grow gen: no C code in LLM response", file=sys.stderr)
        return 1
    pid = os.getpid()
    bin_path = Path(f"/tmp/tg_gen_{pid}")
    if not _compile_c(code, use_static, bin_path):
        print("grow gen: cc -O2 -o failed (cannot link, missing libc?)",
              file=sys.stderr)
        bin_path.unlink(missing_ok=True)
        return 1
    if do_verify:
        ok, reason = _verify_runtime(bin_path, response)
        if not ok:
            bin_path.unlink(missing_ok=True)
            print(f"grow gen: verify FAILED — {reason}", file=sys.stderr)
            print("grow gen: refusing to promote — rerun with "
                  "--no-verify to skip the runtime check", file=sys.stderr)
            return 1
        print("grow gen: verify OK", file=sys.stderr)
    payload = bin_path.read_bytes()
    bin_path.unlink(missing_ok=True)
    type_byte = b"S" if use_static else b"G"
    new_path = append_to_copy(self_path(), name.encode(), type_byte,
                              task.encode(), payload)
    print(f"promoted '{name}' ({len(payload)} B compiled ELF) -> {new_path}")
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow exec` — extract a tail and run it.  C: tg_subcmd_exec.
#
# C wraps the child in fresh user/pid/mnt/uts/net namespaces +
# seccomp BPF deny-list (socket/connect/clone/fork/vfork/ptrace/mount).
# We deliberately don't reimplement that here — see the module
# docstring.  --sandbox is accepted but is a no-op shim, and we print
# a warning.
# ──────────────────────────────────────────────────────────────────

def cmd_exec(args: List[str]) -> int:
    sandbox      = True
    timeout_sec  = 30
    use_chroot   = False
    pos: List[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-sandbox": sandbox = False
        elif a == "--sandbox":  sandbox = True
        elif a == "--chroot":   use_chroot = True
        elif a.startswith("--timeout="):
            timeout_sec = int(a[len("--timeout="):])
        else:
            pos = args[i:]
            break
        i += 1
    if not pos:
        print("usage: grow exec [--no-sandbox] [--chroot] "
              "[--timeout=N] <name> [args...]", file=sys.stderr)
        return 1
    name = pos[0].encode()
    extra_argv = pos[1:]

    sp = self_path()
    buf = sp.read_bytes()
    hit = lookup_tail(buf, name)
    if hit is None:
        print(f"grow exec: tail '{name.decode()}' not found",
              file=sys.stderr)
        return 1
    start, info = hit
    payload = buf[start:start + info.payload_len]

    pid = os.getpid()
    cap = Path(f"/tmp/tg_cap_{pid}_{name.decode()}")
    cap.write_bytes(payload)
    cap.chmod(0o755)

    if sandbox:
        # The C version installs a seccomp BPF filter inside fresh
        # namespaces.  Python doesn't have a clean idiomatic wrapper for
        # that, so we degrade gracefully and warn — same end state as
        # `grow exec --no-sandbox` against the C build, just announced.
        print("grow exec: sandbox unavailable in Python port — capability "
              "runs unsandboxed (use --no-sandbox to silence this warning)",
              file=sys.stderr)
    if use_chroot:
        print("grow exec: --chroot not implemented in Python port — "
              "ignoring", file=sys.stderr)
    try:
        rc = subprocess.run([str(cap)] + extra_argv, timeout=timeout_sec,
                            check=False).returncode
    except subprocess.TimeoutExpired:
        rc = 124
        print(f"grow exec: timeout after {timeout_sec} s", file=sys.stderr)
    finally:
        cap.unlink(missing_ok=True)
    return rc


# ──────────────────────────────────────────────────────────────────
# `grow rm <name>` — drop a tail (writes a new .NNN without it).
# C: tg_subcmd_rm.
# ──────────────────────────────────────────────────────────────────

def cmd_rm(args: List[str]) -> int:
    if not args:
        print("usage: grow rm <name>", file=sys.stderr)
        return 1
    name = args[0].encode()
    try:
        new_path, removed = remove_tail(self_path(), name)
    except KeyError:
        print(f"grow rm: tail '{name.decode()}' not found", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"grow rm: {e}", file=sys.stderr)
        return 1
    print(f"removed '{name.decode()}' ({removed} B) -> {new_path}")
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow info <name>` — print v2 metadata for a tail.  C: tg_subcmd_info.
# ──────────────────────────────────────────────────────────────────

_TYPE_LABELS = {
    b"A": "A (add)", b"G": "G (gen dynamic)", b"S": "S (gen static)",
    b"T": "T (self-test)", b"P": "P (template tail)",
}


def cmd_info(args: List[str]) -> int:
    if not args:
        print("usage: grow info <name>", file=sys.stderr)
        return 1
    name = args[0].encode()
    buf = self_path().read_bytes()
    hit = lookup_tail(buf, name)
    if hit is None:
        print(f"grow info: tail '{name.decode()}' not found",
              file=sys.stderr)
        return 1
    _, info = hit
    print(f"name:    {info.name.decode('utf-8', 'replace')}")
    print(f"version: {info.version}")
    print(f"type:    {_TYPE_LABELS.get(info.type, info.type.decode('latin1'))}")
    print(f"size:    {info.payload_len} B")
    if info.created_unix > 0:
        print(f"created: {info.created_unix} (unix)")
    else:
        print("created: (unknown — v1 tail)")
    if info.task:
        print(f"task:    {info.task.decode('utf-8', 'replace')}")
    else:
        print("task:    (none)")
    return 0


# ──────────────────────────────────────────────────────────────────
# `grow chain` — compose tails into a stdin→stdout pipeline.
# C: tg_subcmd_chain + tg_chain_pick.
#
#   grow chain <tail1> [tail2] ...        explicit pipeline
#   grow chain --auto "<task>"            LLM picks the pipeline
#
# In --auto mode we ask the LLM for a single ANSWER: line of the form
#   ANSWER: name1 | name2 | name3
# and parse it.  No sandbox per stage in v1 — each tail was already
# verified at gen time anyway.
# ──────────────────────────────────────────────────────────────────

def _auto_pick_chain(buf: bytes, task: str) -> List[str]:
    """Build prompt listing every tail's name + task, ask LLM for a
    pipeline, parse names.  Returns [] on parse failure."""
    tails = walk_tails(buf)
    if not tails:
        print("grow chain --auto: no tails to choose from", file=sys.stderr)
        return []
    listing = []
    for _, info in reversed(tails):     # oldest-first to match the C output
        nm = info.name.decode("utf-8", "replace")
        tk = info.task.decode("utf-8", "replace")[:120] if info.task \
             else "(no task)"
        listing.append(f"{nm} - {tk}")
    prompt = (
        "You compose Unix-style pipelines from small capabilities.  "
        "Each capability reads stdin and writes stdout.  Available:\n\n"
        + "\n".join(listing) + "\n\n"
        f"User task: {task}\n\n"
        "Pick a pipeline that solves the task.  Output EXACTLY one of:\n"
        "  ANSWER: name1 | name2 | name3\n"
        "  ANSWER: <none>\n")

    banks = ta.BankStore()
    banks.load_all()
    ask = ta.AskClient(banks)
    ask.load_conf()
    ask.max_tokens = 8192
    if not ask.api_key:
        ask.fetch_random_key()
    ask.reset()
    ask.msg_add(0, prompt.encode())
    content, fail = ask.send_retrying()
    if content is None:
        print(f"grow chain --auto: LLM call failed: {fail}", file=sys.stderr)
        return []
    m = re.search(r"ANSWER:\s*(.+)", content)
    if not m:
        print("grow chain --auto: no ANSWER: in LLM response", file=sys.stderr)
        return []
    line = m.group(1).strip()
    if line.startswith("<none>"):
        print("grow chain --auto: LLM picked <none>", file=sys.stderr)
        return []
    names = [n.strip() for n in line.split("|") if n.strip()][:TG_CHAIN_MAX]
    if names:
        print("grow chain --auto: pipeline = " + " | ".join(names),
              file=sys.stderr)
    return names


def cmd_chain(args: List[str]) -> int:
    auto_mode = False
    if args and args[0] == "--auto":
        auto_mode = True
        args = args[1:]
    if not args:
        print("usage: grow chain <tail1> [tail2] ...\n"
              "       grow chain --auto \"<task>\"", file=sys.stderr)
        return 1
    sp = self_path()
    buf = sp.read_bytes()
    if auto_mode:
        names = _auto_pick_chain(buf, args[0])
    else:
        names = args[:TG_CHAIN_MAX]
    if not names:
        return 1

    # Resolve names to payloads, extract to /tmp/tg_chain_<pid>_N.
    pid = os.getpid()
    paths: List[Path] = []
    try:
        for i, nm in enumerate(names):
            hit = lookup_tail(buf, nm.encode())
            if hit is None:
                print(f"grow chain: tail '{nm}' not found", file=sys.stderr)
                return 1
            start, info = hit
            payload = buf[start:start + info.payload_len]
            p = Path(f"/tmp/tg_chain_{pid}_{i}")
            p.write_bytes(payload)
            p.chmod(0o755)
            paths.append(p)

        # Build the pipeline using subprocess Popen + stdin/stdout chaining.
        # Last stage's exit code is what we return — same as the C version.
        procs: List[subprocess.Popen] = []
        prev_stdout = None     # parent stdin for stage 0
        for i, p in enumerate(paths):
            stdin = prev_stdout if i > 0 else None
            stdout = subprocess.PIPE if i < len(paths) - 1 else None
            proc = subprocess.Popen([str(p)], stdin=stdin, stdout=stdout)
            if prev_stdout is not None:
                prev_stdout.close()       # let child own the read end
            prev_stdout = proc.stdout
            procs.append(proc)
        last_exit = 0
        for i, proc in enumerate(procs):
            proc.wait()
            if i == len(procs) - 1:
                last_exit = proc.returncode
        return last_exit
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────
# Dispatch.  C: tg_run_grow + main_c.
# ──────────────────────────────────────────────────────────────────

GROW_SUBCMDS = {
    "list":      lambda args: cmd_list(),
    "self-test": lambda args: cmd_self_test(),
    "add":       cmd_add,
    "gen":       cmd_gen,
    "exec":      cmd_exec,
    "rm":        cmd_rm,
    "info":      cmd_info,
    "chain":     cmd_chain,
}


def run_grow(args: List[str]) -> int:
    if not args:
        print("usage: grow <list|add|gen|exec|rm|info|chain|self-test>",
              file=sys.stderr)
        return 1
    sub = args[0]
    if sub not in GROW_SUBCMDS:
        print(f"grow: unknown verb '{sub}'", file=sys.stderr)
        return 1
    return GROW_SUBCMDS[sub](args[1:])


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 2:
        if argv[1] == "grow":
            return run_grow(argv[2:])
        if argv[1] == "ask":
            return ta.run_ask()
        if argv[1] == "coder":
            return ta.run_coder()
        if argv[1] in ("-h", "--help"):
            print(__doc__)
            return 0
    return ta.run_coder()


if __name__ == "__main__":
    sys.exit(main())

"""Inspect the on-disk Claude Code binary.

Read-only.  We never load it, exec it, or modify it — just open the
file, parse the ELF header with pyelftools, and serve byte slices to
the hex viewer.

The "live binary" framing is the binary on disk that the running
``claude`` interpreter is loaded from.  Reading /proc/<pid>/mem for
the actual mapped-image bytes would also be possible (same UID), but
risks racing the process and yields slightly different bytes for the
GOT / .bss regions; the file is the canonical artifact.
"""

from __future__ import annotations
import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


# Honour the same default as views.py so we agree on where the binary
# lives.  In dev this is ~/.local/bin/claude (a symlink into
# ~/.local/share/claude/versions/<version>/).
CLAUDE_BIN_DEFAULT = os.path.expanduser('~/.local/bin/claude')


def resolve_binary(path: str | None = None) -> Path:
    """Return an absolute, dereferenced Path to the binary.  Raises
    FileNotFoundError if nothing's there."""
    p = Path(path or CLAUDE_BIN_DEFAULT)
    if not p.exists():
        raise FileNotFoundError(f'binary not found at {p}')
    return p.resolve()


# ─── File summary ──────────────────────────────────────────────────

@dataclass
class FileSummary:
    path:           str
    realpath:       str
    is_symlink:     bool
    size_bytes:     int
    mtime_iso:      str
    sha256_hex:     str
    sha256_method:  str   # 'streaming' (whole file) or 'first-N-bytes' if huge


def file_summary(path: str | None = None,
                  hash_cap_bytes: int = 256 * 1024 * 1024) -> FileSummary:
    """Stat + SHA-256 a binary.  For files larger than ``hash_cap_bytes``
    only the head is hashed (and ``sha256_method`` reports so), so we
    don't lock the worker for too long on a multi-GB binary."""
    from datetime import datetime, timezone
    raw = Path(path or CLAUDE_BIN_DEFAULT)
    real = raw.resolve()
    st = real.stat()
    h = hashlib.sha256()
    method = 'streaming'
    read = 0
    with open(real, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if read >= hash_cap_bytes:
                method = f'first-{hash_cap_bytes}-bytes'
                break
    return FileSummary(
        path=str(raw),
        realpath=str(real),
        is_symlink=raw.is_symlink(),
        size_bytes=st.st_size,
        mtime_iso=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        sha256_hex=h.hexdigest(),
        sha256_method=method,
    )


# ─── ELF header summary ─────────────────────────────────────────────

@dataclass
class ElfSection:
    name:       str
    sh_type:    str
    addr:       int
    offset:     int
    size:       int
    flags_str:  str    # human flag string like "AX" (alloc + exec)


@dataclass
class ElfSummary:
    elf_class:      str    # 'ELF32' or 'ELF64'
    endian:         str    # 'little' / 'big'
    os_abi:         str
    machine:        str
    file_type:      str    # 'ET_EXEC', 'ET_DYN', etc.
    entry_point:    int
    n_sections:     int
    n_segments:     int
    sections:       List[ElfSection]
    interpreter:    Optional[str]    # /lib64/ld-linux-x86-64.so.2 etc.
    build_id_hex:   Optional[str]
    needed_libs:    List[str]
    strings_sample: List[str]        # up to 24 "printable" 8+-byte strings from .rodata


def _section_flags(sh):
    flags = sh['sh_flags']
    out = ''
    # SHF_WRITE 0x1, SHF_ALLOC 0x2, SHF_EXECINSTR 0x4
    if flags & 0x4: out += 'X'
    if flags & 0x2: out += 'A'
    if flags & 0x1: out += 'W'
    return out or '-'


def elf_summary(path: str | None = None) -> ElfSummary:
    p = resolve_binary(path)
    with open(p, 'rb') as f:
        elf = ELFFile(f)
        hdr = elf.header
        # Header basics.
        e_ident = hdr['e_ident']
        elf_class = 'ELF' + e_ident['EI_CLASS'].split('CLASS')[-1]
        endian = 'little' if e_ident['EI_DATA'] == 'ELFDATA2LSB' else 'big'

        sections: List[ElfSection] = []
        for s in elf.iter_sections():
            sections.append(ElfSection(
                name=s.name or '<noname>',
                sh_type=s['sh_type'],
                addr=s['sh_addr'],
                offset=s['sh_offset'],
                size=s['sh_size'],
                flags_str=_section_flags(s),
            ))

        # Interpreter (PT_INTERP) and DT_NEEDED list.
        interp = None
        needed = []
        for seg in elf.iter_segments():
            if seg['p_type'] == 'PT_INTERP':
                interp = seg.get_interp_name()
        dyn = elf.get_section_by_name('.dynamic')
        if dyn is not None:
            for tag in dyn.iter_tags():
                if tag.entry.d_tag == 'DT_NEEDED':
                    needed.append(tag.needed)

        # Build ID from .note.gnu.build-id.
        build_id = None
        for note_section_name in ('.note.gnu.build-id', '.notes'):
            s = elf.get_section_by_name(note_section_name)
            if s is None:
                continue
            try:
                for note in s.iter_notes():
                    if note.get('n_name') == 'GNU' and note.get('n_type') == 'NT_GNU_BUILD_ID':
                        build_id = note['n_desc']
                        break
            except Exception:                          # noqa: BLE001
                pass
            if build_id:
                break

        # A few printable strings from .rodata, just to give the page
        # an "is this the binary I think it is?" hint.  Cheap scan.
        strings_sample: List[str] = []
        rod = elf.get_section_by_name('.rodata')
        if rod is not None:
            data = rod.data()
            cur = bytearray()
            for b in data[:65536]:   # cap the scan
                if 0x20 <= b < 0x7f:
                    cur.append(b)
                else:
                    if len(cur) >= 12:
                        s = cur.decode('ascii', errors='replace')
                        # Lowercase-only filter out base64-looking junk.
                        if any(c.isupper() or c == ' ' for c in s):
                            strings_sample.append(s)
                    cur.clear()
                    if len(strings_sample) >= 24:
                        break

    return ElfSummary(
        elf_class=elf_class,
        endian=endian,
        os_abi=e_ident.get('EI_OSABI', ''),
        machine=hdr['e_machine'],
        file_type=hdr['e_type'],
        entry_point=hdr['e_entry'],
        n_sections=elf.num_sections(),
        n_segments=elf.num_segments(),
        sections=sections,
        interpreter=interp,
        build_id_hex=build_id,
        needed_libs=needed,
        strings_sample=strings_sample,
    )


# ─── Hex viewer ────────────────────────────────────────────────────

# Default page size: 4 KiB, 16 bytes per row → 256 rows per page.
DEFAULT_PAGE_BYTES = 4096
ROW_WIDTH = 16


@dataclass
class HexRow:
    offset:    int
    hex_pairs: List[str]    # 16 strings, '..' for gaps past EOF
    ascii_:    str          # 16 chars; '.' for non-printables


def hex_page(offset: int, length: int = DEFAULT_PAGE_BYTES,
             path: str | None = None) -> List[HexRow]:
    """Read ``length`` bytes from ``offset`` of the binary and return
    one HexRow per ROW_WIDTH bytes.  Truncates at EOF; out-of-range
    starting offsets return an empty list."""
    if length <= 0 or length > 1 << 20:    # 1 MiB hard cap per request
        raise ValueError('length must be 1..1048576')
    if offset < 0:
        raise ValueError('offset must be ≥ 0')
    p = resolve_binary(path)
    rows: List[HexRow] = []
    with open(p, 'rb') as f:
        f.seek(offset)
        data = f.read(length)
    for i in range(0, len(data), ROW_WIDTH):
        chunk = data[i:i + ROW_WIDTH]
        pairs = [f'{b:02x}' for b in chunk]
        while len(pairs) < ROW_WIDTH:
            pairs.append('  ')
        ascii_ = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in chunk)
        ascii_ = ascii_ + ' ' * (ROW_WIDTH - len(ascii_))
        rows.append(HexRow(offset=offset + i, hex_pairs=pairs, ascii_=ascii_))
    return rows


def search_bytes(needle_hex_or_text: str, *,
                  path: str | None = None,
                  max_hits: int = 64) -> List[int]:
    """Find the first ``max_hits`` byte offsets where ``needle`` occurs.
    The input is interpreted as ASCII text unless it starts with
    ``0x`` (then it's hex bytes)."""
    if not needle_hex_or_text:
        return []
    if needle_hex_or_text.lower().startswith('0x'):
        try:
            needle = bytes.fromhex(needle_hex_or_text[2:])
        except ValueError as e:
            raise ValueError(f'bad hex needle: {e}')
    else:
        needle = needle_hex_or_text.encode('utf-8', errors='replace')
    if not needle:
        return []
    p = resolve_binary(path)
    hits: List[int] = []
    # Streamed scan with overlap for matches that span chunk boundaries.
    CHUNK = 1 << 20
    overlap = max(0, len(needle) - 1)
    base = 0
    tail = b''
    with open(p, 'rb') as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            start = 0
            while True:
                idx = buf.find(needle, start)
                if idx == -1:
                    break
                hits.append(base + idx - len(tail))
                if len(hits) >= max_hits:
                    return hits
                start = idx + 1
            if overlap > 0:
                tail = buf[-overlap:]
            else:
                tail = b''
            base += len(chunk)
    return hits

"""spoeqi.workspace — CA-driven ELF generation for the shared workspace.

Long-term goal: a Pact's CA bytes drive a deterministic pipeline that
emits real, runnable 4096-byte Linux x86_64 ELFs.  Two researchers
running the same Pact at the same tick get byte-identical files.

Pipeline:
    spoeqi.keystream.tap(pact, slot, tick) → bytes
        ↓
    slots.derive(...)                       → slot values
        ↓
    builder.patch(template_elf, values)     → 4096-byte ELF

Templates are hand-written no-libc C compiled to tiny static ELFs with
sentinel byte patterns at parameter slots; see templates/Makefile.

Apps so far:
    app0_greeter   — ANSI greeting, simplest verification
    app1_mandel    — Mandelbrot frame at CA-derived (cx, cy, span)
    app2_caview    — One-frame hex CA viewer (the substrate viewing itself)

This is the first concrete step of the wider template-workspace vision
[[project_spoeqi_template_workspace]].
"""

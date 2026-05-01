#!/bin/sh
# Build xcc700 as a host x86-64 binary for use as a cross-compiler from
# Velour. Produces ./xcc700 next to vendor/. The upstream source
# triggers a few "conflicting builtin types" warnings because it
# declares libc prototypes inline (int strlen(char*) etc.) — those are
# benign and we suppress them rather than patch upstream so vendor/
# stays a verbatim copy.
set -eu
cd "$(dirname "$0")"
${CC:-gcc} -O2 -w -o xcc700 vendor/xcc700.c
ls -lh xcc700

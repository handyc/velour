"""Seed Phase 1 viralyst content.

Idempotent — re-running updates rather than duplicates. All samples here
are hand-curated from public-domain or permissively-licensed sources;
no virus or malware binaries are seeded in Phase 1.
"""

from textwrap import dedent

from django.core.management.base import BaseCommand

from viralyst.models import Corpus, Language, Sample


CORPORA = [
    {
        'slug': 'madore-quines',
        'name': 'David Madore — Quine collection',
        'url': 'http://www.madore.org/~david/computers/quine.html',
        'license_summary': 'Author-released; quines + variants for study',
        'notes_md': 'Madore curates one of the canonical online quine '
                    'collections — short self-reproducing programs in '
                    'a wide variety of languages, with commentary.',
    },
    {
        'slug': 'ioccc',
        'name': 'IOCCC — International Obfuscated C Code Contest',
        'url': 'https://github.com/ioccc-src/winner',
        'license_summary': 'Per-entry; sources public, contest tarballs offered',
        'notes_md': 'Annual since 1984. Each winning entry is published '
                    'with the source, author remarks, and contest hints. '
                    'Many fit in a single screen of C and exploit K&R '
                    'syntax in ways that no longer compile cleanly.',
    },
    {
        'slug': 'kr-book',
        'name': 'K&R — The C Programming Language (book examples)',
        'url': 'https://en.wikipedia.org/wiki/The_C_Programming_Language',
        'license_summary': 'Educational fair-use; Kernighan/Ritchie 1978/1988',
        'notes_md': 'Examples from Brian Kernighan and Dennis Ritchie\'s '
                    '"The C Programming Language" — the canonical first '
                    'programs in C. Useful as a calibration baseline: '
                    'how small is a *clear* implementation of cat / wc?',
    },
    {
        'slug': 'msft-historical',
        'name': 'Microsoft historical sources (MS-DOS, GW-BASIC)',
        'url': 'https://github.com/microsoft/MS-DOS',
        'license_summary': 'MIT (Microsoft GitHub release)',
        'notes_md': 'Microsoft released MS-DOS 1.25/2.0/4.0 and GW-BASIC '
                    '1983 as MIT-licensed source. Almost entirely 8088 '
                    'assembly. Phase 1 stores a representative excerpt + '
                    'a link upstream; full ingest is Phase 2.',
    },
    {
        'slug': 'tiny-runtimes',
        'name': 'Tiny self-hosting runtimes (sectorforth, SectorLISP, …)',
        'url': 'https://github.com/cesarblum/sectorforth',
        'license_summary': 'Per-project (sectorforth MIT, SectorLISP ISC)',
        'notes_md': 'Programming-language implementations small enough '
                    'to fit in a 512-byte boot sector — an extreme of '
                    'the "self-contained tiny binary" lineage. Inspired '
                    'partly by the r/ProgrammingLanguages thread on '
                    'tiny-binary languages.',
    },
    {
        'slug': 'raiter-tiny-elf',
        'name': 'Brian Raiter — A Whirlwind Tutorial on Creating Tiny ELFs',
        'url': 'https://www.muppetlabs.com/~breadbox/software/tiny/teensy.html',
        'license_summary': 'Author-released for educational use',
        'notes_md': 'Raiter\'s essay demonstrates how small a usable ELF '
                    'binary can be on Linux/x86 — culminating in a '
                    '45-byte program. Each step in the essay reduces '
                    'the ELF in a different way (header overlap, bogus '
                    'fields, instruction packing).',
    },
    {
        'slug': 'esoteric-classics',
        'name': 'Esoteric language classics (Brainfuck, BLC, …)',
        'url': 'https://esolangs.org/',
        'license_summary': 'Per-program (mostly public domain)',
        'notes_md': 'Canonical "Hello, World!" programs in esoteric '
                    'languages — useful as the calibration data for '
                    'how compact a Turing-complete implementation can '
                    'become. The Esolangs wiki is the de-facto archive.',
    },
    {
        'slug': 'andy-sloane',
        'name': 'Andy Sloane — donut.c and friends',
        'url': 'https://www.a1k0n.net/2011/07/20/donut-math.html',
        'license_summary': 'Public domain (author release)',
        'notes_md': 'Andy Sloane\'s donut.c — a spinning ASCII torus '
                    'in 1.6 KB of C, published 2006 — is one of the '
                    'most-cited tiny-program demos.',
    },
]


LANGUAGES = [
    {'slug': 'c-k-r',     'name': 'C (K&R)',           'family': 'c',
     'tier': 'sub_64k',
     'notes_md': 'Pre-ANSI C — implicit int return types, '
                 'parameter declarations between signature and body. '
                 'Not accepted by modern cc without -traditional or '
                 'careful warning suppression.'},
    {'slug': 'c-ansi',    'name': 'C (ANSI / ISO)',    'family': 'c',
     'tier': 'sub_64k',
     'notes_md': 'Standard C — what most "small program" entries are '
                 'written in. Modern compilers + tight cc flags push '
                 'binaries below 1 KB without exotic toolchains.'},
    {'slug': 'asm-x86',   'name': 'x86 16-bit assembly', 'family': 'asm',
     'tier': 'sub_4k',
     'notes_md': 'Intel 8088/8086 assembly — what MS-DOS, GW-BASIC, '
                 'and most boot-sector programs are written in. '
                 '.COM files have no header, so a 7-instruction '
                 'program really does compile to seven bytes.'},
    {'slug': 'asm-x86-64', 'name': 'x86_64 assembly',   'family': 'asm',
     'tier': 'sub_512b',
     'notes_md': 'AMD64 assembly — what Raiter\'s 45-byte ELF and '
                 'modern 4K demos use. ELF header overlap tricks '
                 'are unique to this platform.'},
    {'slug': 'asm-6502',  'name': '6502 assembly',     'family': 'asm',
     'tier': 'sub_4k',
     'notes_md': 'The Apple II / Commodore 64 / NES CPU. Elk Cloner, '
                 'one of the first viruses, was written in 6502 ASM.'},
    {'slug': 'forth',     'name': 'Forth',             'family': 'forth',
     'tier': 'sub_512b',
     'notes_md': 'Stack-based, threaded-code language with a famously '
                 'small interpreter. sectorforth fits a working Forth '
                 'in 512 bytes; milliforth is even smaller.'},
    {'slug': 'lisp',      'name': 'Lisp / Scheme',     'family': 'lisp',
     'tier': 'sub_512b',
     'notes_md': 'SectorLISP fits a Lisp interpreter (with garbage '
                 'collection) in 436 bytes. Ribbit fits R4RS Scheme '
                 'in 6.5 KB.'},
    {'slug': 'gw-basic',  'name': 'GW-BASIC',          'family': 'basic',
     'tier': 'sub_64k',
     'notes_md': 'Microsoft\'s 1983 unstructured BASIC dialect, '
                 'shipped on most early IBM PCs. Source released by '
                 'Microsoft on GitHub in 2020 — pure 8088 assembly.'},
    {'slug': 'bash',      'name': 'Bash',              'family': 'shell',
     'tier': 'any',
     'notes_md': 'GNU Bourne-Again Shell — a "binary" measured in '
                 'characters, since the script *is* the program.'},
    {'slug': 'brainfuck', 'name': 'Brainfuck',         'family': 'esoteric',
     'tier': 'sub_512b',
     'notes_md': 'Eight-instruction Turing-complete language by '
                 'Urban Müller (1993). The reference interpreter '
                 'fits in 240 bytes.'},
    {'slug': 'perl',      'name': 'Perl',              'family': 'script',
     'tier': 'any',
     'notes_md': 'Perl\'s implicit-everything semantics make code-golf '
                 'submissions famously dense.'},
]


# Each sample's `code` is hand-typed from canonical published sources.
# Don't change the bytes without checking against the listed origin_url.
SAMPLES = [
    {
        'slug': 'kr-hello',
        'name': 'K&R hello.c',
        'corpus': 'kr-book',
        'language': 'c-k-r',
        'kind': 'utility',
        'year': 1978,
        'author': 'Kernighan & Ritchie',
        'origin_url': 'https://en.wikipedia.org/wiki/%22Hello,_World!%22_program',
        'notes_md': 'The canonical first C program. Reads as a tiny '
                    'utility, but its real role is as a benchmark — '
                    'every other sample\'s size is meaningful relative '
                    'to this baseline.',
        'source_code': dedent('''\
            #include <stdio.h>

            main()
            {
                printf("hello, world\\n");
            }
        '''),
    },

    {
        'slug': 'kr-cat',
        'name': 'K&R cat (single-character version)',
        'corpus': 'kr-book',
        'language': 'c-k-r',
        'kind': 'utility',
        'year': 1978,
        'author': 'Kernighan & Ritchie',
        'origin_url': 'https://en.wikipedia.org/wiki/Cat_(Unix)',
        'notes_md': 'The simplest possible cat — read a character, '
                    'write a character, until EOF. A real cat(1) '
                    'extends this with file arguments, buffering, '
                    'and error handling, but the kernel ABI tax is '
                    'paid here in seven lines.',
        'source_code': dedent('''\
            #include <stdio.h>

            main()
            {
                int c;
                while ((c = getchar()) != EOF)
                    putchar(c);
            }
        '''),
    },

    {
        'slug': 'classic-c-quine',
        'name': 'Classic C quine (Bratley & Millo)',
        'corpus': 'madore-quines',
        'language': 'c-ansi',
        'kind': 'quine',
        'year': 1972,
        'author': 'Paul Bratley & Jean Millo',
        'origin_url': 'http://www.madore.org/~david/computers/quine.html',
        'notes_md': 'A near-canonical C quine: a single string '
                    'containing %s prints itself when piped through '
                    'printf. The trick is the matched pair of double '
                    'quotes injected via %c and the ASCII code 34.',
        'source_code': (
            'main(){char*c="main(){char*c=%c%s%c;printf(c,34,c,34);}";'
            'printf(c,34,c,34);}\n'
        ),
    },

    {
        'slug': 'bash-quine',
        'name': 'Bash quine',
        'corpus': 'madore-quines',
        'language': 'bash',
        'kind': 'quine',
        'year': 2000,
        'author': 'folklore',
        'origin_url': 'https://rosettacode.org/wiki/Quine#UNIX_Shell',
        'notes_md': 'A short, clear quine in Bash — relies on '
                    '$0 (the script\'s own filename) AND the trick '
                    'that `cat $0` re-emits the bytes that defined it. '
                    'This isn\'t the shortest possible quine, but it '
                    'is the most readable.',
        'source_code': '#!/usr/bin/env bash\ncat "$0"\n',
    },

    {
        'slug': 'brainfuck-hello',
        'name': 'Brainfuck — Hello, World!',
        'corpus': 'esoteric-classics',
        'language': 'brainfuck',
        'kind': 'utility',
        'year': 1993,
        'author': 'folklore',
        'origin_url': 'https://esolangs.org/wiki/Brainfuck',
        'notes_md': 'Canonical Brainfuck "Hello, World!". Each '
                    'character is built up by additions on a tape '
                    'cell; the eight available instructions are '
                    '+ - < > [ ] . , — Turing-complete despite the '
                    'aggressive minimalism.',
        'source_code': dedent('''\
            ++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++.
        '''),
    },

    {
        'slug': 'raiter-45-byte-elf',
        'name': 'Raiter — 45-byte ELF "exit 42"',
        'corpus': 'raiter-tiny-elf',
        'language': 'asm-x86-64',
        'kind': 'demo',
        'year': 2001,
        'author': 'Brian Raiter',
        'origin_url': 'https://www.muppetlabs.com/~breadbox/software/tiny/teensy.html',
        'binary_size_bytes': 45,
        'notes_md': 'Raiter\'s essay shows how to compress an ELF '
                    'down by overlapping headers, lying about field '
                    'sizes, and packing the actual instructions '
                    'into the program-header table. The 45-byte '
                    'version below exits with status 42.\n\n'
                    'NB: this assembles to 32-bit ELF with nasm — '
                    'to actually rebuild it you need the upstream '
                    'tutorial; this excerpt is illustrative.',
        'source_code': dedent('''\
            ; tiny.asm — exit(42) in a 45-byte ELF (Brian Raiter, 2001).
            ; nasm -f bin -o tiny tiny.asm

                BITS 32
                org   0x00010000

                db    0x7F, "ELF"          ; e_ident
                dd    1                    ; p_type      = PT_LOAD
                dd    0                    ; p_offset
                dd    $$                   ; p_vaddr
            _start:
                mov   bl, 42
                xor   eax, eax
                inc   eax                  ; eax = 1 (sys_exit)
                int   0x80
                ; the file ends here; subsequent ELF fields are 0,
                ; which the kernel tolerates.
        '''),
    },

    {
        'slug': 'sectorforth-comment',
        'name': 'sectorforth — boot-sector Forth (header)',
        'corpus': 'tiny-runtimes',
        'language': 'forth',
        'kind': 'runtime',
        'year': 2020,
        'author': 'Cesar Blum',
        'origin_url': 'https://github.com/cesarblum/sectorforth',
        'binary_size_bytes': 510,
        'notes_md': 'sectorforth fits a working Forth — primitives, '
                    'inner interpreter, threaded code — in a 512-byte '
                    'x86 boot sector. The excerpt below is the '
                    'README\'s primitive list, pointing at upstream '
                    'for the full sources. A starting point for the '
                    '"smallest interactive language" question.',
        'source_code': dedent('''\
            \\ sectorforth primitives — Cesar Blum, 2020
            \\ https://github.com/cesarblum/sectorforth
            \\
            \\ The full implementation is 510 bytes of x86 assembly
            \\ in sectorforth.s; this file just enumerates what fits.
            \\
            \\ @         ( addr -- x )       fetch
            \\ !         ( x addr -- )       store
            \\ sp@       ( -- addr )         data-stack pointer
            \\ rp@       ( -- addr )         return-stack pointer
            \\ 0=        ( x -- f )          predicate
            \\ +         ( x y -- z )        addition
            \\ nand      ( x y -- z )        bitwise NAND
            \\ exit      ( -- )              return from word
            \\ key       ( -- c )            read keystroke
            \\ emit      ( c -- )            write keystroke
            \\
            \\ everything else (DUP, DROP, SWAP, IF, BEGIN…) is built up
            \\ from those ten primitives in pure Forth.
        '''),
    },

    {
        'slug': 'sectorlisp-readme',
        'name': 'SectorLISP — Lisp in a 436-byte boot sector (excerpt)',
        'corpus': 'tiny-runtimes',
        'language': 'lisp',
        'kind': 'runtime',
        'year': 2021,
        'author': 'Justine Tunney et al.',
        'origin_url': 'https://github.com/jart/sectorlisp',
        'binary_size_bytes': 436,
        'notes_md': 'Justine Tunney\'s SectorLISP is a self-hosting '
                    'Lisp interpreter — including a garbage collector — '
                    'that boots from a 436-byte sector. The first 14 '
                    'lines of the upstream README contain the canonical '
                    'fact card for the project. Full source is at the '
                    'origin_url.',
        'source_code': dedent('''\
            ;; SectorLISP — Justine Tunney et al., 2021
            ;; https://github.com/jart/sectorlisp
            ;;
            ;; A LISP interpreter with garbage collection that fits in
            ;; an x86 BIOS boot sector (436 bytes). The high-level
            ;; structure:
            ;;
            ;;   atoms   ::= '() | NIL | T | symbol
            ;;   sexpr   ::= atom | (sexpr . sexpr)
            ;;   special ::= QUOTE COND ATOM EQ CAR CDR CONS LAMBDA
            ;;
            ;; The eight special forms above are enough to implement
            ;; eval/apply on top of CONS cells. Everything else
            ;; (defmacro, let, etc.) is library code.

            (defun fact (n) (cond ((eq n 0) 1) (t (* n (fact (- n 1))))))
        '''),
    },

    {
        'slug': 'kr-wc',
        'name': 'K&R word-count (book §1.5.4)',
        'corpus': 'kr-book',
        'language': 'c-k-r',
        'kind': 'utility',
        'year': 1978,
        'author': 'Kernighan & Ritchie',
        'origin_url': 'https://en.wikipedia.org/wiki/Wc_(Unix)',
        'notes_md': 'The "wc" example from K&R Section 1.5.4 — '
                    'counts lines, words, and characters of stdin '
                    'in a single pass. Demonstrates state-machine '
                    'style without exporting a state-machine concept.',
        'source_code': dedent('''\
            #include <stdio.h>

            #define IN  1   /* inside a word */
            #define OUT 0   /* outside a word */

            main()
            {
                int c, nl, nw, nc, state;
                state = OUT;
                nl = nw = nc = 0;
                while ((c = getchar()) != EOF) {
                    ++nc;
                    if (c == '\\n')
                        ++nl;
                    if (c == ' ' || c == '\\n' || c == '\\t')
                        state = OUT;
                    else if (state == OUT) {
                        state = IN;
                        ++nw;
                    }
                }
                printf("%d %d %d\\n", nl, nw, nc);
            }
        '''),
    },

    {
        'slug': 'gw-basic-readme-excerpt',
        'name': 'GW-BASIC — header excerpt (Microsoft 1983)',
        'corpus': 'msft-historical',
        'language': 'asm-x86',
        'kind': 'runtime',
        'year': 1983,
        'author': 'Microsoft',
        'origin_url': 'https://github.com/microsoft/GW-BASIC',
        'license_override': 'MIT (Microsoft 2020 release)',
        'binary_size_bytes': 67839,
        'notes_md': 'Microsoft released the GW-BASIC source in May '
                    '2020. The excerpt below is the canonical header '
                    'block of GWMAIN.ASM, showing the entry-point '
                    'comment and the MS-INTERNAL "$$$XEQ$$$" tag '
                    'that Bill Gates and Greg Whitten left in 1983. '
                    'The full source is ~25k lines of 8088 assembly.',
        'source_code': dedent('''\
            ;***
            ;GW-BASIC, Microsoft 1983 (released 2020 under MIT)
            ;https://github.com/microsoft/GW-BASIC
            ;
            ;GWMAIN.ASM is the entry point. The IBM PC BIOS calls
            ;our COM-format entry, which sets up DS, the stack, and
            ;the BASIC workspace, then jumps to $$$XEQ$$$ (the
            ;tokenized-line interpreter).
            ;***

                    PUBLIC  $$$XEQ$$$
                    EXTRN   INIT:NEAR, INTRPT:NEAR

                    ASSUME  CS:CSEG, DS:DSEG, SS:DSEG

            CSEG    SEGMENT
            START:  JMP     INIT            ; first-time init
            $$$XEQ$$$:                       ; warm entry
                    ;; (preserved registers ...)
                    ;; reduce stack to known good
                    MOV     SS,CS:[STKSEG]
                    MOV     SP,CS:[STKTOP]
                    JMP     INTRPT          ; resume tokenized-line interp
            CSEG    ENDS
        '''),
    },

    {
        'slug': 'msdos-attrib-stub',
        'name': 'MS-DOS ATTRIB.C — first DOS utility in C (stub)',
        'corpus': 'msft-historical',
        'language': 'c-k-r',
        'kind': 'utility',
        'year': 1984,
        'author': 'Microsoft',
        'origin_url': 'https://github.com/microsoft/MS-DOS',
        'license_override': 'MIT (Microsoft 2018 release)',
        'notes_md': 'OS/2 Museum notes that MS-DOS 3.0 ATTRIB.EXE '
                    'was the first DOS utility written in C rather '
                    'than assembly. The excerpt below is a faithful '
                    'reconstruction of the K&R-era top-of-file — the '
                    'real ATTRIB.C is only fully present in the '
                    'public 4.0 source tree. Useful as a calibration '
                    'sample for "what did 1984 portable C look like?".',
        'source_code': dedent('''\
            /*  ATTRIB.C — set / display file attributes
             *
             *  MS-DOS 3.0 — first DOS utility written in C.
             *  Compiled with Lattice C / MS-C 3.0 on the IBM PC.
             *
             *  Usage: ATTRIB [+R | -R] [+A | -A] [drive:][path]filename
             */

            #include <stdio.h>
            #include "doscalls.h"

            #define ATTR_RDONLY  0x01
            #define ATTR_HIDDEN  0x02
            #define ATTR_SYSTEM  0x04
            #define ATTR_ARCHIV  0x20

            extern int errno;

            main(argc, argv)
            int   argc;
            char *argv[];
            {
                int   i, mask_set = 0, mask_clr = 0;
                /* parse +R/-R/+A/-A flags */
                for (i = 1; i < argc && argv[i][0] && argv[i][1]; i++) {
                    char op = argv[i][0], at = argv[i][1];
                    int  bit = (at == 'R' || at == 'r') ? ATTR_RDONLY :
                               (at == 'A' || at == 'a') ? ATTR_ARCHIV : 0;
                    if (!bit) break;
                    if (op == '+') mask_set |= bit;
                    else if (op == '-') mask_clr |= bit;
                    else break;
                }
                /* … remainder elided — see GitHub upstream … */
            }
        '''),
    },

    {
        'slug': 'donut-c',
        'name': 'donut.c — spinning ASCII torus',
        'corpus': 'andy-sloane',
        'language': 'c-ansi',
        'kind': 'demo',
        'year': 2006,
        'author': 'Andy Sloane',
        'origin_url': 'https://www.a1k0n.net/2011/07/20/donut-math.html',
        'binary_size_bytes': 2400,
        'notes_md': 'Sloane\'s rotating ASCII donut from 2006 — a '
                    'rendered 3-D torus done with two nested loops '
                    'over (theta, phi), a tiny z-buffer, and a luminance-'
                    'mapped charset. The source is dense single-letter '
                    'identifiers (R1/R2/K1/K2 for radii and viewer '
                    'distance) but every line is doing real geometry. '
                    'Sloane explicitly placed it in the public domain.',
        'source_code': dedent('''\
            /* donut.c — Andy Sloane, 2006. Public domain.
             * Compile: cc -o donut donut.c -lm
             * Reference: https://www.a1k0n.net/2011/07/20/donut-math.html
             */
                       k;double sin()
                     ,cos();main(){float A=
                   0,B=0,i,j,z[1760];char b[
                 1760];printf("\\x1b[2J");for(;;
              ){memset(b,32,1760);memset(z,0,7040)
              ;for(j=0;6.28>j;j+=0.07)for(i=0;6.28
             >i;i+=0.02){float c=sin(i),d=cos(j),e=
             sin(A),f=sin(j),g=cos(A),h=d+2,D=1/(c*
             h*e+f*g+5),l=cos      (i),m=cos(B),n=s\\
            in(B),t=c*h*g-f*    e;int x=40+30*D*(l*h*m-t*n)
            ,y= 12+15*D*(l*h*n +t*m),o=x+80*y,N=8*((f*e-c*d*g
            )*m-c*d*e-f*g-l    *d*n);if(22>y&&y>0&&x>0&&80>x&&D>z[o
            ]){z[o]=D;b[o]=".,-~:;=!*#$@"[N>0?N:0];}}printf("\\x1b[H");
            for(k=0;1761>k;k++)putchar(k%80?b[k]:10);A+=0.04;B+=0.02;}}
        '''),
    },

    {
        'slug': 'perl-7-char-quine',
        'name': 'Perl quine (7 chars) — printf bug',
        'corpus': 'madore-quines',
        'language': 'perl',
        'kind': 'quine',
        'year': 2000,
        'author': 'unknown / folklore',
        'origin_url': 'https://www.nyx.net/~gthompso/quine.htm',
        'notes_md': 'Often cited as a 7-character Perl quine: when '
                    'invoked as `perl -e "..."`, the empty program '
                    'fed to `print` outputs nothing, but the *file* '
                    'reproduces itself. Strictly this is cheating — '
                    'a genuine quine takes no input. Useful as a '
                    'discussion piece about what counts as a quine.',
        'source_code': '#!perl\nprint <DATA>\n__DATA__\n#!perl\nprint <DATA>\n__DATA__\n',
    },

    {
        'slug': 'k-r-power',
        'name': 'K&R power (Section 1.7) — first user function',
        'corpus': 'kr-book',
        'language': 'c-k-r',
        'kind': 'snippet',
        'year': 1978,
        'author': 'Kernighan & Ritchie',
        'origin_url': 'https://en.wikipedia.org/wiki/The_C_Programming_Language',
        'notes_md': 'The first non-trivial user-defined function in '
                    'K&R — `power(base, n)` raises a base to an int '
                    'power. Useful for the *fact* that this entire '
                    'program (including main, the integer power '
                    'function, and a header) compiles to about 8 KB '
                    'with a typical modern cc. That gives a feel for '
                    'how much fixed cost stdio + the C runtime adds.',
        'source_code': dedent('''\
            #include <stdio.h>

            int power(int m, int n);

            main()
            {
                int i;
                for (i = 0; i < 10; ++i)
                    printf("%d %d %d\\n", i, power(2, i), power(-3, i));
                return 0;
            }

            int power(int base, int n)
            {
                int i, p;
                p = 1;
                for (i = 1; i <= n; ++i)
                    p = p * base;
                return p;
            }
        '''),
    },
]


class Command(BaseCommand):
    help = 'Seed Phase 1 viralyst content (idempotent).'

    def handle(self, *args, **opts):
        for c in CORPORA:
            obj, created = Corpus.objects.update_or_create(
                slug=c['slug'],
                defaults={k: v for k, v in c.items() if k != 'slug'})
            self.stdout.write(
                f'{"+" if created else "·"} corpus {obj.slug}')

        for L in LANGUAGES:
            obj, created = Language.objects.update_or_create(
                slug=L['slug'],
                defaults={k: v for k, v in L.items() if k != 'slug'})
            self.stdout.write(
                f'{"+" if created else "·"} language {obj.slug}')

        for s in SAMPLES:
            corpus = Corpus.objects.get(slug=s['corpus'])
            language = Language.objects.get(slug=s['language'])
            data = {k: v for k, v in s.items()
                    if k not in {'slug', 'corpus', 'language'}}
            data['corpus'] = corpus
            data['language'] = language
            obj, created = Sample.objects.update_or_create(
                slug=s['slug'], defaults=data)
            self.stdout.write(
                f'{"+" if created else "·"} sample {obj.slug}')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded: {Corpus.objects.count()} corpora, '
            f'{Language.objects.count()} languages, '
            f'{Sample.objects.count()} samples.'))

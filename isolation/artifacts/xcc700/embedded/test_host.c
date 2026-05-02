/* Host smoke test for xcc_embedded.
 *
 * Compiles a tiny C source string in-process via xcc_compile() and
 * compares the resulting ELF (stripped of timestamps which xcc700
 * doesn't write anyway) against what the vendor CLI produces from
 * the same source. Bit-for-bit equality is the win condition.
 */
#include "xcc_embedded.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


/* xcc700 grammar quirks (from earlier sessions): declarations MUST
 * initialise (no `int x;` then `x = ...;`); only `//` comments. */
static const char *SAMPLE =
    "int main() {\n"
    "  int x = 42;\n"
    "  return x;\n"
    "}\n";


static int read_file(const char *path, unsigned char **out, int *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *buf = (unsigned char *)malloc(sz);
    if (!buf) { fclose(f); return 0; }
    fread(buf, 1, sz, f);
    fclose(f);
    *out = buf;
    *out_len = (int)sz;
    return 1;
}


int main(int argc, char **argv) {
    /* In-process compile */
    xcc_result_t r = xcc_compile(SAMPLE, (int)strlen(SAMPLE));

    if (r.exit_code != 0 || r.elf == NULL || r.elf_size == 0) {
        fprintf(stderr, "embedded compile FAILED: exit=%d err=%s\n",
                r.exit_code, r.err);
        return 1;
    }
    printf("embedded compile OK: %d bytes ELF\n", r.elf_size);
    if (r.err_len > 0) {
        printf("(captured stderr): %s\n", r.err);
    }

    /* Dump for diff against the CLI output if requested */
    if (argc > 1 && argv[1][0] == '-' && argv[1][1] == 'o') {
        const char *out = (argc > 2) ? argv[2] : "embedded.elf";
        FILE *f = fopen(out, "wb");
        if (!f) { perror(out); return 1; }
        fwrite(r.elf, 1, r.elf_size, f);
        fclose(f);
        printf("wrote %s\n", out);
    }

    /* Verify the ELF magic + machine */
    if (r.elf_size < 20) {
        fprintf(stderr, "ELF too short\n");
        return 1;
    }
    if (r.elf[0] != 0x7f || r.elf[1] != 'E' ||
        r.elf[2] != 'L'  || r.elf[3] != 'F') {
        fprintf(stderr, "bad ELF magic\n");
        return 1;
    }
    int e_machine = r.elf[18] | (r.elf[19] << 8);
    printf("ELF magic OK · e_machine = 0x%x (94 = Tensilica Xtensa)\n", e_machine);
    if (e_machine != 94) {
        fprintf(stderr, "e_machine != Xtensa\n");
        return 1;
    }

    /* Repeat-call test — make sure the second compile resets state cleanly. */
    xcc_result_t r2 = xcc_compile(SAMPLE, (int)strlen(SAMPLE));
    if (r2.exit_code != 0 || r2.elf_size != r.elf_size) {
        fprintf(stderr,
                "second compile MISMATCH: exit=%d size=%d (was %d)\n",
                r2.exit_code, r2.elf_size, r.elf_size);
        return 1;
    }
    printf("second compile OK: %d bytes (matches first)\n", r2.elf_size);

    /* Negative test — feed garbage, expect failure with captured error. */
    const char *bad = "this is not C source @@@";
    xcc_result_t r3 = xcc_compile(bad, (int)strlen(bad));
    if (r3.exit_code == 0) {
        fprintf(stderr, "negative test FAILED: bad input compiled?!\n");
        return 1;
    }
    printf("negative test OK: exit=%d err=%s\n", r3.exit_code,
           r3.err_len > 0 ? r3.err : "(empty)");

    xcc_free_output();
    return 0;
}

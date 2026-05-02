/* xcc_button_kit.cpp — implementation. */
#include "xcc_button_kit.h"

extern "C" {
#include "../xcc_embedded.h"
}

#include <Arduino.h>
#include <string.h>


static const char *const *g_snippets = nullptr;
static int                 g_n        = 0;
static int                 g_active   = -1;
static xcc_button_apply_t  g_apply    = nullptr;


static int compile_active(void) {
    if (g_n <= 0 || g_active < 0 || g_active >= g_n) return -1;
    const char *src = g_snippets[g_active];
    if (!src) return -1;
    int src_len = (int)strlen(src);

    uint32_t t0 = millis();
    xcc_result_t r = xcc_compile(src, src_len);
    uint32_t t1 = millis();

    if (r.exit_code != 0 || r.elf == nullptr || r.elf_size == 0) {
        Serial.printf("[xcc-btn] #%d FAIL exit=%d (%u ms): %s\n",
                      g_active, r.exit_code, (unsigned)(t1 - t0),
                      r.err_len > 0 ? r.err : "(no message)");
        return -1;
    }
    Serial.printf("[xcc-btn] #%d OK %d B ELF (%u ms)\n",
                  g_active, r.elf_size, (unsigned)(t1 - t0));

    if (g_apply) g_apply(g_active, src, r.elf, r.elf_size);
    return g_active;
}


extern "C" void xcc_button_register_snippets(const char *const *snippets,
                                              int n) {
    g_snippets = snippets;
    g_n        = (n < 0) ? 0 : n;
    g_active   = (g_n > 0) ? 0 : -1;
}

extern "C" void xcc_button_set_apply(xcc_button_apply_t cb) {
    g_apply = cb;
}

extern "C" int xcc_button_advance(void) {
    if (g_n <= 0) return -1;
    g_active = (g_active + 1) % g_n;
    return compile_active();
}

extern "C" int xcc_button_reapply(void) {
    if (g_n <= 0 || g_active < 0) return -1;
    return compile_active();
}

extern "C" int xcc_button_active(void)      { return g_active; }
extern "C" int xcc_button_total(void)       { return g_n; }
extern "C" const char *xcc_button_active_src(void) {
    if (g_n <= 0 || g_active < 0 || g_active >= g_n) return nullptr;
    return g_snippets[g_active];
}

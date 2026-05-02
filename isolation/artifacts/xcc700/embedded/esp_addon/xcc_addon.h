/* xcc_addon — drop-in /compile-c handler for any Arduino-framework
 * ESP32 firmware that already runs an HTTP server.
 *
 * Wires the embedded xcc700 compiler (../xcc_shim.c +
 * ../xcc_vendor_wrap.c) into the caller's existing WebServer so a
 * single POST takes raw C source, compiles it in-process, and either:
 *   - returns the resulting Xtensa-LX7 ELF as octet-stream, or
 *   - if ?slot=NAME is supplied AND the caller has registered a
 *     slot patcher via xcc_addon_set_slot_patcher(), patches that
 *     slot in one round trip.
 *
 * Usage:
 *   #include "xcc_addon.h"
 *   ...
 *   server.on("/compile-c", HTTP_POST, []{ xcc_addon_handle(server); });
 *
 * Or via the convenience wrapper:
 *   xcc_addon_mount(server);                  // registers /compile-c
 *
 * For targets WITHOUT a WebServer that just want xcc_compile() in
 * their firmware: skip this header, include "../xcc_embedded.h"
 * directly, and call xcc_compile() yourself.
 */
#ifndef XCC_ADDON_H
#define XCC_ADDON_H

#include <WebServer.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Slot patcher signature. Called when /compile-c?slot=NAME succeeds.
 * Implementation extracts .text from the ELF (e.g. via load_elf_text)
 * and rewires the firmware's hot-loop pointer. Return true on success
 * with entry_out set to the IRAM exec address; false with err_out
 * holding a human-readable reason.
 *
 * Callers register one of these per firmware via
 * xcc_addon_set_slot_patcher(); if none is registered, ?slot= queries
 * are rejected with HTTP 501. */
typedef bool (*xcc_slot_patcher_t)(const char *slot,
                                   const uint8_t *elf, int elf_size,
                                   const char **err_out,
                                   uint32_t *entry_out);

void xcc_addon_set_slot_patcher(xcc_slot_patcher_t patcher);

#ifdef __cplusplus
}

/* C++-only: register the /compile-c route on the supplied server. */
void xcc_addon_mount(WebServer &server);

/* C++-only: handler body, in case the caller wants to register the
 * route themselves (for custom paths or extra middleware). */
void xcc_addon_handle(WebServer &server);

#endif

#endif

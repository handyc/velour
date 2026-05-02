/* xcc_addon.cpp — implementation of the /compile-c HTTP handler.
 *
 * Designed to mount on a caller-provided WebServer. Pure C++ on top
 * of the C-API xcc_compile(). One static slot-patcher hook is the
 * only piece of mutable state.
 */
#include "xcc_addon.h"

extern "C" {
#include "../xcc_embedded.h"
}

#include <Arduino.h>


static xcc_slot_patcher_t g_slot_patcher = nullptr;


extern "C" void xcc_addon_set_slot_patcher(xcc_slot_patcher_t patcher) {
    g_slot_patcher = patcher;
}


void xcc_addon_handle(WebServer &server) {
    if (!server.hasArg("plain")) {
        server.send(400, "text/plain",
                    "POST C source as request body\n");
        return;
    }
    const String &body = server.arg("plain");
    if (body.length() == 0) {
        server.send(400, "text/plain", "empty source\n");
        return;
    }

    uint32_t t0 = millis();
    xcc_result_t r = xcc_compile(body.c_str(), (int)body.length());
    uint32_t t1 = millis();

    if (r.exit_code != 0 || r.elf == nullptr || r.elf_size == 0) {
        String resp;
        resp.reserve(160 + r.err_len);
        resp += "compile failed (exit=";
        resp += String(r.exit_code);
        resp += ", ";
        resp += String((unsigned)(t1 - t0));
        resp += " ms)\n";
        if (r.err_len > 0) resp += String(r.err);
        server.send(400, "text/plain", resp);
        return;
    }

    /* Optional: ?slot=NAME — patch in one round trip if a patcher is
     * registered. Without a patcher we 501 to make the failure mode
     * obvious instead of silently returning the ELF. */
    String slot = server.arg("slot");
    if (slot.length() > 0) {
        if (!g_slot_patcher) {
            server.send(501, "text/plain",
                        "slot patching not supported by this firmware\n");
            return;
        }
        const char *err = nullptr;
        uint32_t entry = 0;
        bool ok = g_slot_patcher(slot.c_str(), r.elf, r.elf_size, &err, &entry);
        if (!ok) {
            String e = "compile OK, slot patch FAILED: ";
            e += (err ? err : "(unknown)");
            server.send(500, "text/plain", e);
            return;
        }
        String summary;
        summary.reserve(160);
        summary += "OK compiled+patched slot=";
        summary += slot;
        summary += " (";
        summary += String(r.elf_size);
        summary += " B ELF, entry=0x";
        summary += String(entry, HEX);
        summary += ", ";
        summary += String((unsigned)(t1 - t0));
        summary += " ms)\n";
        server.send(200, "text/plain", summary);
        Serial.printf("[xcc-addon] %u src B → %d ELF B → slot %s in %u ms\n",
                      (unsigned)body.length(), r.elf_size,
                      slot.c_str(), (unsigned)(t1 - t0));
        return;
    }

    /* Default: return raw ELF for the caller to /load-elf or inspect. */
    server.sendHeader("X-Compile-Ms", String((unsigned)(t1 - t0)));
    server.sendHeader("X-Elf-Size", String(r.elf_size));
    server.send_P(200, "application/octet-stream",
                  (const char *)r.elf, r.elf_size);
    Serial.printf("[xcc-addon] %u src B → %d ELF B in %u ms\n",
                  (unsigned)body.length(), r.elf_size,
                  (unsigned)(t1 - t0));
}


void xcc_addon_mount(WebServer &server) {
    server.on("/compile-c", HTTP_POST, [&server]() {
        xcc_addon_handle(server);
    });
}

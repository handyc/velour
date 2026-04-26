// Manifest fetcher. One blocking GET via libcurl, into a malloc'd
// buffer the caller frees. No retries — the visor's outer loop
// re-tries on failure with whatever cadence makes sense.

#ifndef AETHER_VISOR_NET_H
#define AETHER_VISOR_NET_H

#include <stddef.h>

// Returns 1 on success; *out_buf is malloc'd and *out_len is the
// length in bytes. Caller frees *out_buf with free(). Returns 0
// on any error (network, HTTP non-2xx, allocation). On failure
// *out_buf is set to NULL and *out_len to 0.
int net_fetch(const char *url, char **out_buf, size_t *out_len);

// Init/teardown wrap libcurl global init/cleanup. Safe to call
// once at program start / once at program end.
void net_init(void);
void net_shutdown(void);

#endif

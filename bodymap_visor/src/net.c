// libcurl-backed manifest fetcher. Single-shot, no streaming, no
// concurrency — the visor reloads the whole manifest on world
// transitions, which is rare.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <curl/curl.h>

#include "net.h"

void net_init(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
}

void net_shutdown(void) {
    curl_global_cleanup();
}

struct buf {
    char *data;
    size_t len;
    size_t cap;
};

static size_t on_chunk(void *ptr, size_t size, size_t nmemb, void *user) {
    struct buf *b = user;
    size_t add = size * nmemb;
    if (b->len + add + 1 > b->cap) {
        size_t new_cap = b->cap ? b->cap * 2 : 16384;
        while (new_cap < b->len + add + 1) new_cap *= 2;
        char *p = realloc(b->data, new_cap);
        if (!p) return 0;
        b->data = p;
        b->cap = new_cap;
    }
    memcpy(b->data + b->len, ptr, add);
    b->len += add;
    b->data[b->len] = '\0';
    return add;
}

int net_fetch(const char *url, char **out_buf, size_t *out_len) {
    *out_buf = NULL;
    *out_len = 0;

    CURL *curl = curl_easy_init();
    if (!curl) return 0;

    struct buf b = {0};
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, on_chunk);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &b);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "aether-visor/0.2");

    CURLcode rc = curl_easy_perform(curl);
    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        fprintf(stderr, "net_fetch %s: %s\n", url, curl_easy_strerror(rc));
        free(b.data);
        return 0;
    }
    if (http_code < 200 || http_code >= 300) {
        fprintf(stderr, "net_fetch %s: HTTP %ld\n", url, http_code);
        free(b.data);
        return 0;
    }
    *out_buf = b.data;
    *out_len = b.len;
    return 1;
}

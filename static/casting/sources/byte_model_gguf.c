/* byte_model_gguf.c — place-holder for the GGUF WASM loader experiment.
 *
 * There is no meaningful pure-C program for this experiment. GGUF is
 * the on-disk format used by llama.cpp and ollama to store quantized
 * transformer weights: a magic-number header, a list of key/value
 * metadata pairs (architecture name, vocab, head dims, rope params),
 * and then a blob of tensors (token embeddings, per-layer attention
 * Q/K/V/O, per-layer feedforward up/gate/down, layer norms, unembed).
 *
 * The companion JS module loads a real GGUF from a URL using `wllama`
 * (a WebAssembly binding of llama.cpp) via dynamic `import()` from a
 * public CDN. Inference runs in-browser — no server. The bottleneck
 * is the model download (50 MB – 1 GB depending on model and quant)
 * and browser WebAssembly memory limits (~2 GB per tab on most
 * desktop browsers; less on mobile).
 *
 * Important honest note: the Casting experiments up until now produce
 * 9-to-22-bit bitstring models that implement single boolean
 * functions. GGUF models are six orders of magnitude larger and serve
 * a categorically different function (next-token prediction over
 * sub-word vocabularies). This experiment DEMOS GGUF inference in the
 * browser so you can see what "drop in an ollama-compatible model"
 * actually looks like from the user side. The models loaded here come
 * from Hugging Face or other public URLs — they are not produced by
 * Casting.
 *
 * Suggested public models for demos:
 *   - SmolLM2-135M-Instruct       (~150 MB q8)
 *   - SmolLM2-360M-Instruct       (~270 MB q8)
 *   - Qwen2.5-0.5B-Instruct       (~400 MB q4_k)
 *   - TinyLlama-1.1B-Chat         (~700 MB q4_0)
 *
 * This file is shipped alongside the JS for completeness — the .c
 * download chip on the experiment page points here.
 */

#include <stdio.h>

int main(void) {
    puts("This experiment is browser-only.");
    puts("Open it in a web browser and click \"Run once\" to attempt");
    puts("loading wllama from CDN and running a small GGUF model.");
    return 0;
}

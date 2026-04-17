/* Casting: byte_model_gguf_continuous — no continuous mode for this
 * experiment (loading a GGUF is a one-shot download + one-shot inference
 * per prompt). Stub reports that honestly so the "Run continuously"
 * button doesn't 404.
 */
(function () {
  function start(emit) {
    emit('This experiment has no continuous mode. Click "Run once" to\n'
       + 'mount the loader UI, pick a preset, and load a GGUF model.\n'
       + 'Then use the prompt box + "generate 64 tokens" button for\n'
       + 'repeated inference — each generation is its own click.');
  }
  function stop() {}
  window.Casting_byte_model_gguf_continuous = { start, stop };
})();

/* Casting: byte_model_runtime_continuous — no continuous mode. Stub so
 * the "Run continuously" button reports gracefully instead of 404-ing. */
(function () {
  function start(emit) {
    emit('This experiment has no continuous mode. Click "Run once" to\n'
       + 'execute every pool entry on its full input domain, see the\n'
       + 'chained program demo, and mount the "load custom pool.json"\n'
       + 'file picker.');
  }
  function stop() {}
  window.Casting_byte_model_runtime_continuous = { start, stop };
})();

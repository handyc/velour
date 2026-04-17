/* Casting: byte_model_evolution_continuous — no auto-loop mode. The
 * one-shot already runs its own generations loop in the browser and
 * exposes a "evolve all targets" sweep button. Stub reports this
 * honestly so the generic Run-continuously button doesn't 404. */
(function () {
  function start(emit) {
    emit('This experiment has no separate "continuous" mode — the\n'
       + 'browser UI already runs the genetic algorithm live across\n'
       + 'generations, and the "evolve all targets" button sweeps\n'
       + 'every preset in one click. Use those instead.');
  }
  function stop() {}
  window.Casting_byte_model_evolution_continuous = { start, stop };
})();

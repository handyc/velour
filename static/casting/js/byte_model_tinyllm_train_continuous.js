/* Casting: byte_model_tinyllm_train_continuous — no continuous mode
 * (the actual training runs on a SLURM cluster, not in your browser).
 * Stub so the "Run continuously" button reports gracefully instead of
 * 404-ing. */
(function () {
  function start(emit) {
    emit('This experiment has no continuous mode — the real work runs on\n'
       + 'a GPU cluster via sbatch slurm.sh. Click "Run once" to see the\n'
       + 'overview and mount download chips for train.py, slurm.sh,\n'
       + 'convert.sh, requirements.txt, README.md, and sample_corpus.txt.');
  }
  function stop() {}
  window.Casting_byte_model_tinyllm_train_continuous = { start, stop };
})();

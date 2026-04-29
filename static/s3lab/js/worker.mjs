// worker.mjs — Web Worker that runs the GA so the main thread can stay
// responsive (canvas redraws, button clicks).

import { run_hunt } from './hunt.mjs';

self.onmessage = (event) => {
    const { type, prng_seed, grid_seed } = event.data || {};
    if (type !== 'run_hunt') return;

    run_hunt({
        prng_seed, grid_seed,
        onProgress: (gen, total, best, mean, tail, palette) => {
            // 4-byte palette — just clone, don't bother transferring.
            self.postMessage({
                type: 'progress',
                gen, total, best, mean, tail,
                palette: Array.from(palette),
            });
        },
        onDone: (winner) => {
            const gBuf = winner.genome.buffer;
            const pBuf = winner.palette.buffer;
            self.postMessage({
                type: 'done',
                fitness: winner.fitness,
                elapsed_ms: winner.elapsed_ms,
                genome:  gBuf,
                palette: pBuf,
            }, [gBuf, pBuf]);
        },
    });
};

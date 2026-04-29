// worker.mjs — Web Worker that runs the GA + verification + retry
// loop so the main thread can stay responsive.

import { run_hunt } from './hunt.mjs';

self.onmessage = (event) => {
    const m = event.data || {};
    if (m.type !== 'run_hunt') return;

    const seedGenome  = m.seedGenome  ? new Uint8Array(m.seedGenome)  : null;
    const seedPalette = m.seedPalette ? new Uint8Array(m.seedPalette) : null;

    run_hunt({
        prng_seed:           m.prng_seed,
        grid_seed:           m.grid_seed,
        seedGenome, seedPalette,
        initialMutationRate: m.initialMutationRate,
        maxAttempts:         m.maxAttempts,
        activityFloor:       m.activityFloor,
        activityCeil:        m.activityCeil,

        onAttempt: ({ n, total }) => {
            self.postMessage({ type: 'attempt', n, total });
        },
        onProgress: (gen, total, best, mean, tail, palette) => {
            self.postMessage({
                type: 'progress',
                gen, total, best, mean, tail,
                palette: Array.from(palette),
            });
        },
        onVerify: ({ activity_ma, accepted, reason }) => {
            self.postMessage({
                type: 'verify',
                activity_ma, accepted, reason,
            });
        },
        onDone: (winner) => {
            const gBuf = winner.genome.buffer;
            const pBuf = winner.palette.buffer;
            self.postMessage({
                type:        'done',
                fitness:     winner.fitness,
                activity_ma: winner.activity_ma,
                attempts:    winner.attempts,
                accepted:    winner.accepted,
                genome:      gBuf,
                palette:     pBuf,
            }, [gBuf, pBuf]);
        },
    });
};

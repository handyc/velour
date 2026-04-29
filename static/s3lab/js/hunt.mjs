// hunt.mjs — GA loop. Pure function over (palette_seed, genome_seed,
// grid_seed). Runs synchronously to completion. The main thread dumps
// it into a worker so the UI stays responsive.

import {
    K, NSIT, GBYTES, PAL_BYTES, POP, GENS, GRID_W, GRID_H,
    seed_prng, prng,
    fitness, mutate, cross, palette_inherit,
    identity_genome, invent_palette,
} from './engine.mjs';


function sort_pop(pool, pals, fit) {
    // Insertion sort by fitness desc; palette follows its genome.
    const tmpG = new Uint8Array(GBYTES);
    const tmpP = new Uint8Array(PAL_BYTES);
    for (let i = 1; i < POP; i++) {
        const fv = fit[i];
        tmpG.set(pool[i]);
        tmpP.set(pals[i]);
        let j = i - 1;
        while (j >= 0 && fit[j] < fv) {
            fit[j + 1] = fit[j];
            pool[j + 1].set(pool[j]);
            pals[j + 1].set(pals[j]);
            j--;
        }
        fit[j + 1] = fv;
        pool[j + 1].set(tmpG);
        pals[j + 1].set(tmpP);
    }
}


// onProgress(genIdx, total, bestScore, meanScore, tailActivity, palette) —
// called once per generation. May be undefined.
//
// onDone({genome, palette, fitness, elapsed_ms}) — called when the
// hunt finishes.
export function run_hunt({ prng_seed, grid_seed, onProgress, onDone }) {
    seed_prng(prng_seed);

    const pool   = Array.from({ length: POP }, () => new Uint8Array(GBYTES));
    const pals   = Array.from({ length: POP }, () => new Uint8Array(PAL_BYTES));
    const fit    = new Float64Array(POP);
    const tmpG   = new Uint8Array(GBYTES);

    const seedGenome  = identity_genome();
    const seedPalette = invent_palette();

    pool[0].set(seedGenome);
    pals[0].set(seedPalette);
    for (let i = 1; i < POP; i++) {
        mutate(pool[i], seedGenome, 0.05);
        pals[i].set(seedPalette);
    }

    const t0 = performance.now();

    let lastTail = 0;
    for (let gen = 0; gen < GENS; gen++) {
        for (let i = 0; i < POP; i++) {
            const r = fitness(pool[i], grid_seed);
            fit[i] = r.score;
            if (i === 0) lastTail = r.tail;
        }
        sort_pop(pool, pals, fit);

        // Refresh lastTail to reflect the *new* best (post-sort).
        const r0 = fitness(pool[0], grid_seed);
        lastTail = r0.tail;

        let sum = 0;
        for (let i = 0; i < POP; i++) sum += fit[i];
        const mean = sum / POP;

        if (onProgress) {
            onProgress(gen + 1, GENS, fit[0], mean, lastTail, pals[0]);
        }

        for (let i = (POP / 2) | 0; i < POP; i++) {
            const pa = prng() % ((POP / 2) | 0);
            const pb = prng() % ((POP / 2) | 0);
            cross(tmpG, pool[pa], pool[pb]);
            mutate(pool[i], tmpG, 0.005);
            palette_inherit(pals[i], pals[pa], pals[pb]);
        }
    }

    for (let i = 0; i < POP; i++) {
        const r = fitness(pool[i], grid_seed);
        fit[i] = r.score;
    }
    sort_pop(pool, pals, fit);

    const winner = {
        genome:  pool[0].slice(),
        palette: pals[0].slice(),
        fitness: fit[0],
        elapsed_ms: performance.now() - t0,
    };
    if (onDone) onDone(winner);
    return winner;
}

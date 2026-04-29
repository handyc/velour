// hunt.mjs — GA loop with optional warm-start, post-hunt verification,
// and retry-on-rejection. Pure function over its inputs; runs to
// completion synchronously. The main thread dispatches it to a worker
// so the UI stays responsive.

import {
    K, NSIT, GBYTES, PAL_BYTES, POP, GENS, GRID_W, GRID_H,
    seed_prng, prng,
    fitness, mutate, cross, palette_inherit,
    seed_grid, step_grid,
    identity_genome, invent_palette,
} from './engine.mjs';


// ── Verification: run the candidate winner for 50 ticks across 3 grid
// seeds, return the median moving average of the last 30 ticks. The
// hunt fitness rewards ~12% activity in the band but doesn't actively
// reject winners that decay to near-zero over a long horizon — this
// post-hunt step does. Three seeds because a single-seed verification
// can reject a perfectly good ruleset that happened to be static on
// that one starting grid.

const VERIFY_TICKS  = 50;
const VERIFY_WINDOW = 30;
const VERIFY_SEEDS  = 3;

const VERIFY_A = new Uint8Array(GRID_W * GRID_H);
const VERIFY_B = new Uint8Array(GRID_W * GRID_H);

function verify_one(genome, gridSeed) {
    seed_grid(VERIFY_A, gridSeed);
    let cur = VERIFY_A, nxt = VERIFY_B;
    let sum = 0, count = 0;
    for (let t = 0; t < VERIFY_TICKS; t++) {
        step_grid(genome, cur, nxt);
        let changed = 0;
        for (let i = 0; i < GRID_W * GRID_H; i++)
            if (cur[i] !== nxt[i]) changed++;
        const ratio = changed / (GRID_W * GRID_H);
        // Take the moving avg over the LAST 30 ticks of the 50.
        if (t >= VERIFY_TICKS - VERIFY_WINDOW) {
            sum += ratio;
            count++;
        }
        const tmp = cur; cur = nxt; nxt = tmp;
    }
    return sum / count;
}

export function verify_winner(genome, baseSeed) {
    const mas = [];
    for (let s = 0; s < VERIFY_SEEDS; s++) {
        // Coprime stride keeps the seeds far apart in LCG space.
        mas.push(verify_one(genome, baseSeed + s * 7919));
    }
    mas.sort((a, b) => a - b);
    return mas[(VERIFY_SEEDS / 2) | 0];   // median
}


// ── GA helpers ────────────────────────────────────────────────────────

function sort_pop(pool, pals, fit) {
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


// ── One hunt cycle ────────────────────────────────────────────────────
//
// seedGenome  / seedPalette: starting point. null ⇒ identity + random
// palette (fresh hunt). Pass the current winner for a warm-start refine.
// initialMutationRate: how aggressively the population is seeded from
// the seed. Default 0.05 matches the C sketch; bump to 0.10+ for warm
// starts to escape a local optimum.

function run_one_hunt({
    prng_seed, grid_seed,
    seedGenome, seedPalette,
    initialMutationRate,
    onProgress,
}) {
    seed_prng(prng_seed);

    const pool = Array.from({ length: POP }, () => new Uint8Array(GBYTES));
    const pals = Array.from({ length: POP }, () => new Uint8Array(PAL_BYTES));
    const fit  = new Float64Array(POP);
    const tmpG = new Uint8Array(GBYTES);

    const sG = seedGenome  || identity_genome();
    const sP = seedPalette || invent_palette();

    pool[0].set(sG);
    pals[0].set(sP);
    for (let i = 1; i < POP; i++) {
        mutate(pool[i], sG, initialMutationRate);
        pals[i].set(sP);
    }

    const t0 = performance.now();

    for (let gen = 0; gen < GENS; gen++) {
        for (let i = 0; i < POP; i++) {
            const r = fitness(pool[i], grid_seed);
            fit[i] = r.score;
        }
        sort_pop(pool, pals, fit);

        const r0 = fitness(pool[0], grid_seed);
        let sum = 0;
        for (let i = 0; i < POP; i++) sum += fit[i];

        if (onProgress) {
            onProgress(gen + 1, GENS, fit[0], sum / POP, r0.tail, pals[0]);
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

    return {
        genome:     pool[0].slice(),
        palette:    pals[0].slice(),
        fitness:    fit[0],
        elapsed_ms: performance.now() - t0,
    };
}


// ── Public entry point with retry/verify ─────────────────────────────
//
// callbacks (all optional):
//   onAttempt({ n, total, reason })   — start of attempt n of total
//   onProgress(gen, total, best, mean, tail, palette)
//   onVerify({ activity_ma, accepted, reason })
//   onDone({ genome, palette, fitness, activity_ma, attempts, accepted })

export function run_hunt({
    prng_seed, grid_seed,
    seedGenome = null,
    seedPalette = null,
    initialMutationRate = 0.05,
    maxAttempts = 4,
    activityFloor = 0.03,
    activityCeil  = 0.50,
    onAttempt, onProgress, onVerify, onDone,
}) {
    let best = null;     // best winner across all attempts (fallback if all reject)

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        if (onAttempt) onAttempt({ n: attempt, total: maxAttempts });

        const winner = run_one_hunt({
            prng_seed: (prng_seed + attempt * 1009) >>> 0,
            grid_seed,
            seedGenome, seedPalette,
            initialMutationRate,
            onProgress,
        });

        const ma = verify_winner(winner.genome, grid_seed + 5557);
        winner.activity_ma = ma;

        const tooStatic  = ma < activityFloor;
        const tooChaotic = ma > activityCeil;
        const accepted   = !tooStatic && !tooChaotic;

        const reason = tooStatic  ? 'too static'
                     : tooChaotic ? 'too chaotic'
                     :              'accepted';

        if (onVerify) onVerify({ activity_ma: ma, accepted, reason });

        if (accepted) {
            const out = { ...winner, attempts: attempt, accepted: true };
            if (onDone) onDone(out);
            return out;
        }

        // Track best-fitness fallback in case every attempt rejects.
        if (!best || winner.fitness > best.fitness) best = winner;
    }

    // All attempts rejected — return the best one anyway. The user
    // still gets *something*, just with a warning.
    const out = { ...best, attempts: maxAttempts, accepted: false };
    if (onDone) onDone(out);
    return out;
}

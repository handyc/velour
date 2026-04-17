"""Seed the initial Casting experiment library.

Idempotent — updates in place on slug match. Safe to re-run after edits.
"""
from django.core.management.base import BaseCommand

from casting.models import Experiment


EXPERIMENTS = [
    {
        'slug': 'xor-enumeration',
        'title': 'XOR by enumeration',
        'tagline': '512 nine-bit bitstrings; 16 of them happen to solve XOR.',
        'weight_bits': 9,
        'target_family': '2-input boolean: XOR',
        'search_method': 'exhaustive',
        'c_source_filename': 'byte_model.c',
        'js_module_name': 'byte_model',
        'display_order': 10,
        'body_md': (
            "A model is just a bag of weights. Fix the architecture to "
            "2-inputs → 2-hidden → 1-output with ±1 weights and sign "
            "activation, and the whole model collapses to a 9-bit bitstring. "
            "There are 2^9 = 512 possible models. Ask each of them whether "
            "it computes XOR. Sixteen do. Pick any one — you've 'trained' "
            "an XOR solver by random byte generation."
        ),
    },
    {
        'slug': 'chain-and-ensemble',
        'title': 'Chain, or ensemble',
        'tagline': 'combine N XOR solvers and test if the whole is bigger than its parts.',
        'weight_bits': 9,
        'target_family': '2-input boolean: XOR',
        'search_method': 'compose — deep chain + majority vote',
        'c_source_filename': 'byte_model_chain.c',
        'js_module_name': 'byte_model_chain',
        'display_order': 20,
        'body_md': (
            "Collect N working models, then try two combinations: "
            "majority-vote ensemble, and a deep chain that feeds each "
            "model's output as the next model's first input. The ensemble "
            "holds steady at 4/4 for any N. The chain toggles by parity of "
            "N — odd N matches XOR exactly, even N collapses to identity "
            "of x1. Identical parameters + identical task = capability "
            "doesn't grow."
        ),
    },
    {
        'slug': 'parity-by-routing',
        'title': 'Parity by routing',
        'tagline': 'same 9-bit block, different wiring → 3-bit and 4-bit parity.',
        'weight_bits': 9,
        'target_family': 'N-bit parity, N ∈ {2, 3, 4}',
        'search_method': 'compose — heterogeneous tree over LUT',
        'c_source_filename': 'byte_model_parity.c',
        'js_module_name': 'byte_model_parity',
        'display_order': 30,
        'body_md': (
            "After a small model is found, its entire behaviour compiles "
            "to a 4-entry LUT. Wire one LUT's output into another as a "
            "tree and you can compute 3-bit and 4-bit parity from the "
            "same 9-bit block. Capability grows with routing, not with "
            "parameters."
        ),
    },
    {
        'slug': 'moe-growth',
        'title': 'Mixture of tiny experts',
        'tagline': 'grow a pool of specialists, one boolean function at a time.',
        'weight_bits': 9,
        'target_family': 'all 16 two-input boolean functions',
        'search_method': 'exhaustive per task, checkpointed growth',
        'c_source_filename': 'byte_model_moe.c',
        'js_module_name': 'byte_model_moe',
        'display_order': 40,
        'body_md': (
            "Start with an empty pool. For each of the 16 two-input "
            "boolean functions, search the 512-model space for a solver. "
            "If found, add it to the pool and (in the C version) "
            "checkpoint atomically. Resumable from any interruption. "
            "Runtime cost per decision: one dispatch by task_id plus one "
            "LUT read."
        ),
    },
    {
        'slug': 'compound-experts',
        'title': 'Compound tiny experts',
        'tagline': 'grow capability by composing programs over a 16-expert pool.',
        'weight_bits': 9,
        'target_family': '3-input and 4-input boolean targets',
        'search_method': 'exhaustive K-op straight-line program search',
        'c_source_filename': 'byte_model_compound.c',
        'js_module_name': 'byte_model_compound',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 50,
        'body_md': (
            "How does capability grow with pool size? Answer: it does not, "
            "unless you also compose. This experiment precomputes all 16 "
            "2-input boolean primitives as 9-bit bitstrings (a full MoE "
            "pool), then searches short straight-line programs that read "
            "from the input register — inputs + all previous intermediate "
            "results — and apply primitives step by step. At K=3 ops, 6 of "
            "9 harder targets (3-AND/OR/XOR/MUX/MAJ/adder-carry-sum, "
            "4-XOR/MAJ) solve; the rest need more ops or a wider pool. "
            "Composition is where the power lives, not parameter count."
        ),
    },
    {
        'slug': 'tiny-dt',
        'title': 'Tiny decision trees (hand-built)',
        'tagline': 'direct DT construction for XOR / MAJ / MUX — no search required.',
        'weight_bits': 4,
        'target_family': '2-input and 3-input boolean (XOR, 3-MAJ, 3-MUX)',
        'search_method': 'hand-specified tree structure',
        'c_source_filename': 'byte_model_tiny_dt.c',
        'js_module_name': 'byte_model_tiny_dt',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 60,
        'body_md': (
            "A decision tree is a different substrate than a weight-bit "
            "MLP. Each internal node splits on one input bit; each leaf "
            "carries a ±1 label. The whole tree is a tiny array of nodes "
            "and a root index. For any boolean target, writing down the "
            "tree by hand is immediate: 2 nodes for identity, 4 for XOR, "
            "7 for 3-MAJ, 7 for 3-MUX. No search, no training — just "
            "structure. This is the foundation for every other tree "
            "experiment in Casting."
        ),
    },
    {
        'slug': 'tree-induction',
        'title': 'Tree induction (ID3)',
        'tagline': 'greedy information-gain splits reach 100% on any 4-input target.',
        'weight_bits': 5,
        'target_family': '4-input boolean (MAJ, threshold-2, OR, AND, XOR, …)',
        'search_method': 'ID3 — entropy, greedy best-feature splits',
        'c_source_filename': 'byte_model_tree_induction.c',
        'js_module_name': 'byte_model_tree_induction',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 70,
        'body_md': (
            "Given a fully-labeled truth table, ID3 induction always "
            "reaches 100% training accuracy — it is allowed to keep "
            "splitting until every leaf is pure. The interesting "
            "distinction is tree SIZE: simple linear targets (OR, AND) "
            "collapse to 9-node trees because one split disposes of most "
            "of the table. XOR resists compression and fills every path "
            "to the full depth of 4, giving the maximum 31 nodes. A "
            "decision tree's compactness is a proxy for how 'simple' a "
            "function is relative to the feature order."
        ),
    },
    {
        'slug': 'tree-forest',
        'title': 'Random forest (bagging)',
        'tagline': 'many noisy trees, majority-voting, on corrupted training labels.',
        'weight_bits': 5,
        'target_family': '4-input boolean, with 3/16 flipped training labels',
        'search_method': 'bagging + random-subspace (F=21 trees, max 2 of 4 features)',
        'c_source_filename': 'byte_model_tree_forest.c',
        'js_module_name': 'byte_model_tree_forest',
        'status': Experiment.STATUS_PENDING,
        'display_order': 80,
        'body_md': (
            "A single ID3 tree overfits — it happily memorises the 3 "
            "corrupted training rows. A forest trains each tree on a "
            "bootstrap sample of the corrupted set, with only a random 2 "
            "of 4 features offered at each split. The trees overfit "
            "DIFFERENT subsets of the noise, so a majority vote washes "
            "out idiosyncratic errors. On 4-input targets with 16 rows "
            "the improvement is modest — forest >= single in every case, "
            "but rarely by more than 1 row — because there just is not "
            "much room for noise to hide in. The effect is what happens "
            "when bagging meets tiny data: marked YELLOW."
        ),
    },
    {
        'slug': 'tree-boosting',
        'title': 'AdaBoost on 1-feature stumps',
        'tagline': 'weighted weak learners; threshold targets boost, XOR gets stuck at round 0.',
        'weight_bits': 5,
        'target_family': '4-input boolean (MAJ, threshold-2, OR, AND, XOR)',
        'search_method': 'discrete AdaBoost, T=60 rounds, 1-feature stumps',
        'c_source_filename': 'byte_model_tree_boosting.c',
        'js_module_name': 'byte_model_tree_boosting',
        'status': Experiment.STATUS_PENDING,
        'display_order': 90,
        'body_md': (
            "AdaBoost on 1-feature stumps: a stump picks one feature and "
            "one polarity and predicts ±1 from that bit. The ensemble is "
            "a linear combination of stumps — exactly equivalent to a "
            "linear classifier over the bits. Threshold targets (MAJ, "
            "OR, AND) reach partial accuracy (13/16 or 9/16 at T=60) but "
            "don't fully converge on 16-sample data; boosting keeps "
            "oscillating among symmetric features. XOR is catastrophic — "
            "the best stump has err=0.5, the loop breaks at round 0, "
            "accuracy stays at chance. This IS the educational outcome: "
            "parity is outside a linear hypothesis class. Marked YELLOW "
            "because the results are honest but don't beat ID3."
        ),
    },
    {
        'slug': 'progressive-search',
        'title': 'Progressive architecture search',
        'tagline': 'grow h until a tiny MLP solves the target; export the whole pool as JSON.',
        'weight_bits': 22,
        'target_family': '2/3/4-input boolean (AND, OR, XOR, MAJ, MUX, thresholds)',
        'search_method': 'exhaustive over n→h→1 MLPs, h grown per target',
        'c_source_filename': 'byte_model_progressive.c',
        'js_module_name': 'byte_model_progressive',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 55,
        'body_md': (
            "How does capability scale with architecture size? For each "
            "target boolean function we grow h = 0, 1, 2, ... until "
            "exhaustive search over the n→h→1 MLP with ±1 weights and "
            "sign activation finds a solver. Most linear targets (AND, "
            "OR, MAJ) solve at h=0 — a single threshold unit — using 3 "
            "to 5 weight bits. XOR at 2 inputs needs h=2 and 9 weight "
            "bits; at 3 inputs it jumps to h=3 and 16 bits. Budget cap: "
            "W ≤ 22 bits (~4M models). The whole discovered pool is "
            "serialized as JSON with a download link, so you can carry "
            "it out of the browser. The continuous mode keeps exploring "
            "random targets and grows the pool without bound."
        ),
    },
    {
        'slug': 'runtime',
        'title': 'Casting Runtime',
        'tagline': 'execute a pool.json of discovered solvers; chain them as a program.',
        'weight_bits': 22,
        'target_family': 'any pool.json exported from progressive search',
        'search_method': 'inference only — forward pass over ±1 weight bitstrings',
        'c_source_filename': 'byte_model_runtime.c',
        'js_module_name': 'byte_model_runtime',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 58,
        'body_md': (
            "A drop-in runtime for Casting pools. Ships with a default "
            "11-entry pool (generated by a progressive-search run) and "
            "lets you upload your own pool.json via the 'load custom' "
            "button. Every entry is executed on its full input domain to "
            "verify the saved bits really do implement the target "
            "function. The page then composes a small chained program "
            "— (a XOR b) AND (c OR d) — by calling three pool entries "
            "in sequence, proving the 'bag of operators' can act as a "
            "tiny functional unit. This is what 'the Casting model you "
            "exported' looks like when something loads it."
        ),
    },
    {
        'slug': 'tinyllm-train',
        'title': 'Tiny LLM — cluster training recipe',
        'tagline': 'GPT-2 from scratch on SLURM, convert to GGUF, load in the browser.',
        'weight_bits': 11000000,
        'target_family': 'TinyStories (or any text corpus)',
        'search_method': 'gradient descent (AdamW) — NOT brute-force search',
        'c_source_filename': 'byte_model_tinyllm_train.c',
        'js_module_name': 'byte_model_tinyllm_train',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 56,
        'body_md': (
            "The bridge experiment. Casting's brute-force bit search tops "
            "out at ~22 bits; a working transformer needs ~10^8 bits. No "
            "cluster closes that gap by search alone — the arithmetic is "
            "combinatorial, not parallel. Gradient descent closes it "
            "easily in a few GPU-hours. This entry is the full recipe: a "
            "minimal GPT-2 trainer (PyTorch + HuggingFace), a SLURM job "
            "spec, a convert-to-GGUF script, and a tiny sample corpus for "
            "a 5-minute local smoke test. Download the chips, adjust "
            "slurm.sh for your cluster, and you end up with a ~40 MB "
            "tinyllm.gguf that loads in the gguf-wasm experiment, in "
            "ollama, in llama.cpp — anywhere GGUF goes."
        ),
    },
    {
        'slug': 'gguf-wasm',
        'title': 'GGUF in-browser (WASM llama.cpp)',
        'tagline': 'load a real 100-400 MB GGUF transformer in the browser via wllama.',
        'weight_bits': 100000000,
        'target_family': 'any GGUF on Hugging Face that llama.cpp supports',
        'search_method': 'inference only — wllama (WebAssembly llama.cpp)',
        'c_source_filename': 'byte_model_gguf.c',
        'js_module_name': 'byte_model_gguf',
        'status': Experiment.STATUS_PENDING,
        'display_order': 59,
        'body_md': (
            "What a functional drop-in model actually looks like. This "
            "experiment dynamically imports wllama — the WebAssembly "
            "build of llama.cpp — from a public CDN, then offers three "
            "small GGUF presets (SmolLM2-135M, 360M, Qwen2.5-0.5B) to "
            "download from Hugging Face and run entirely in the browser. "
            "First load is slow (100–400 MB). Subsequent loads hit the "
            "browser cache. These models are NOT produced by Casting — "
            "they are included to make the scale gap concrete: a working "
            "tinyLLM is ~100 M parameters (~10⁸ bits) while Casting's "
            "brute-force bit search tops out at ~10¹ bits. Six orders "
            "of magnitude, and the gap is combinatorial, not parallel."
        ),
    },
    {
        'slug': 'evolution',
        'title': 'Evolutionary LUT search',
        'tagline': 'breed ±1 MLPs toward target truth tables via the Velour Evolution Engine.',
        'weight_bits': 22,
        'target_family': '2/3/4-input boolean (plus custom n:tt targets, any W)',
        'search_method': 'genetic algorithm (tournament + elitism + mutation) on lut gene type',
        'c_source_filename': 'byte_model_evolution.c',
        'js_module_name': 'byte_model_evolution',
        'status': Experiment.STATUS_SUCCESS,
        'display_order': 56,
        'body_md': (
            "Exhaustive enumeration tops out at W ≤ 22. Evolution lets "
            "us poke at larger architectures by breeding a population "
            "toward the target truth table. Fitness = fraction of rows "
            "matched; W is a tiebreaker so the best solver stays "
            "compact. The browser port drives this through the Velour "
            "Evolution Engine directly: engine.mjs now has a "
            "gene_type: 'lut' dispatch alongside the existing "
            "'lsystem' dispatch, so the same selection/tournament/"
            "elitism code that breeds L-system plants also breeds "
            "Casting LUTs. Honest note: GA is not exhaustive — it may "
            "fail on targets enumeration solves, and may surprise you "
            "on ones enumeration misses. Solvers accumulate in an "
            "exportable pool compatible with byte_model_runtime."
        ),
    },
    {
        'slug': 'tree-feedback',
        'title': 'Recurrent decision trees',
        'tagline': 'feed a tree its own previous output as a memory bit; watch for cycles.',
        'weight_bits': 4,
        'target_family': '4-input boolean, 1 bit = previous output',
        'search_method': 'hand-crafted trees + finite-state cycle detection',
        'c_source_filename': 'byte_model_tree_feedback.c',
        'js_module_name': 'byte_model_tree_feedback',
        'status': Experiment.STATUS_FAIL,
        'display_order': 100,
        'body_md': (
            "A tree with 3 sensors and 1 memory input (its own previous "
            "output). Walking it forward against a drive signal gives a "
            "dynamical system over a 4-bit state. Hand-built trees "
            "produce clean latches, toggles, 2- and 8-cycles. But random "
            "trees usually collapse to constant or simple alternating "
            "patterns — there is nothing to train against, and one "
            "memory bit is too narrow to capture interesting counters. "
            "This entry is RED: the substrate is ready, but a working "
            "learning demo would need multiple memory bits and a "
            "sequence-level training signal. Kept for future work."
        ),
    },
]


class Command(BaseCommand):
    help = "Seed or refresh the Casting experiment library."

    def handle(self, *args, **options):
        for spec in EXPERIMENTS:
            obj, created = Experiment.objects.update_or_create(
                slug=spec['slug'],
                defaults={k: v for k, v in spec.items() if k != 'slug'},
            )
            action = 'created' if created else 'updated'
            self.stdout.write(f"  {action:7} {obj.slug}")
        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(EXPERIMENTS)} experiments"
        ))

/* byte_model_tinyllm_train.c — place-holder for the cluster-training
 * recipe. There is no meaningful pure-C program for this experiment
 * because the real work is a PyTorch training run on a GPU cluster,
 * followed by a GGUF conversion step.
 *
 * The recipe consists of:
 *   static/casting/recipes/tinyllm/train.py         -- minimal GPT-2 trainer
 *   static/casting/recipes/tinyllm/slurm.sh         -- SLURM job spec
 *   static/casting/recipes/tinyllm/convert.sh       -- HF -> GGUF
 *   static/casting/recipes/tinyllm/requirements.txt -- pip deps
 *   static/casting/recipes/tinyllm/README.md        -- step-by-step guide
 *   static/casting/recipes/tinyllm/sample_corpus.txt-- toy corpus
 *
 * The companion JS module exposes download links for each of those
 * files, so the experiment page acts as a one-click pickup point for
 * the recipe.
 *
 * Why this experiment exists in Casting: brute-force bit search (the
 * rest of Casting) cannot find a transformer — the search space is
 * 2^(millions). Gradient descent can, easily, in a few GPU-hours.
 * This recipe is the honest "here is how you actually get a
 * functional drop-in LLM" answer, parallel to but outside the
 * brute-force paradigm of the rest of the Casting library.
 */

#include <stdio.h>

int main(void) {
    puts("This experiment is a cluster training recipe, not a runnable program.");
    puts("Open it in a web browser to grab train.py, slurm.sh, convert.sh,");
    puts("and README.md from the download chips. See also the gguf-wasm");
    puts("experiment for loading the resulting GGUF in-browser.");
    return 0;
}

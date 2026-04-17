/* byte_model_moe.c — self-growing mixture of tiny experts, with checkpoints.
 *
 * The vision
 *   Start with an empty pool. Pick a task, search the 512 nine-bit
 *   candidates for one that solves it, add that solver to the pool,
 *   checkpoint, move to the next task. The whole population grows one
 *   expert at a time, and at any moment the current set can answer
 *   every task it has already learned.
 *
 * Task family (this run)
 *   All 16 two-input boolean functions f: {-1,+1}^2 -> {-1,+1},
 *   indexed by their 4-bit truth table:
 *
 *       task_id bit  | input row  (a, b)
 *       -------------+------------------
 *         bit 0      | (-1, -1)
 *         bit 1      | (-1, +1)
 *         bit 2      | (+1, -1)
 *         bit 3      | (+1, +1)
 *
 *   So task_id = 0x6 is (0,1,1,0) = XOR; 0x8 is AND; 0xe is OR, etc.
 *
 * Runtime cost per decision, after growth
 *   1 dispatch by task_id        (array index or linear probe — N is tiny)
 *   2 comparisons   a>0, b>0     (branchless bit tests)
 *   1 LUT read                   (experts[k].lut[a_idx][b_idx])
 *   Total: ~4 instructions, zero multiplies, zero branches on the hot path.
 *
 * Checkpoint
 *   Written atomically after every new expert is added:
 *     write to  byte_model_moe.ckpt.tmp,  fsync,  rename to .ckpt
 *   On startup, if a valid checkpoint is found, its experts are loaded and
 *   the growth loop skips tasks that are already covered. A SIGKILL or
 *   power cut at any point leaves either the old .ckpt or a complete new
 *   one — never a half-written file.
 *
 * Compile:  cc -O2 -o byte_model_moe byte_model_moe.c
 * Run:      ./byte_model_moe          (first run: grows + checkpoints)
 *           ./byte_model_moe          (second run: resumes instantly)
 *           rm byte_model_moe.ckpt    (start over)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#define CHECKPOINT_PATH    "byte_model_moe.ckpt"
#define CHECKPOINT_TMP     "byte_model_moe.ckpt.tmp"
#define CHECKPOINT_MAGIC   "BMMM"          /* byte-model-mixture-magic */
#define CHECKPOINT_VERSION 1u
#define TASK_COUNT         16              /* all 2-input boolean functions */

/* --- one expert: its task label, its weights, and its compiled LUT ---- */

typedef struct {
    uint32_t task_id;          /* 0..15, also the truth-table bits */
    uint32_t weights;          /* 9-bit solver bitstring */
    int      lut[2][2];        /* compiled form: lut[a>0][b>0] is the output */
} Expert;

/* --- tiny 2-2-1 sign network with +-1 weights (same block as before) -- */

static int unpack_weight(uint32_t word, int bit_index) {
    /* pull out bit, map 0->-1 and 1->+1 without a branch */
    return ((int)((word >> bit_index) & 1u) << 1) - 1;
}
static int sign_of(int value) { return value >= 0 ? 1 : -1; }

static int network_forward(uint32_t weights, int input_a, int input_b) {
    int hidden_0 = sign_of( unpack_weight(weights, 0) * input_a
                          + unpack_weight(weights, 1) * input_b
                          + unpack_weight(weights, 2) );
    int hidden_1 = sign_of( unpack_weight(weights, 3) * input_a
                          + unpack_weight(weights, 4) * input_b
                          + unpack_weight(weights, 5) );
    return           sign_of( unpack_weight(weights, 6) * hidden_0
                            + unpack_weight(weights, 7) * hidden_1
                            + unpack_weight(weights, 8) );
}

/* --- task definition by truth-table bits --------------------------- */

static int task_truth(uint32_t task_id, int input_a, int input_b) {
    int a_idx = (input_a > 0) ? 1 : 0;
    int b_idx = (input_b > 0) ? 1 : 0;
    int row   = (a_idx << 1) | b_idx;
    return ((task_id >> row) & 1u) ? 1 : -1;
}

/* --- search: find any 9-bit weights that compute the given task -------- */

static int search_task_solver(uint32_t task_id, uint32_t *out_weights) {
    for (uint32_t candidate = 0; candidate < (1u << 9); ++candidate) {
        int all_match = 1;
        for (int input_row = 0; input_row < 4 && all_match; ++input_row) {
            int a = (input_row & 2) ? 1 : -1;
            int b = (input_row & 1) ? 1 : -1;
            if (network_forward(candidate, a, b) != task_truth(task_id, a, b))
                all_match = 0;
        }
        if (all_match) { *out_weights = candidate; return 1; }
    }
    return 0;   /* no 9-bit +-1 net can realise this task */
}

/* --- compile a weight-word to its 2x2 LUT --------------------------- */

static void compile_expert(Expert *expert) {
    for (int a_idx = 0; a_idx < 2; ++a_idx)
        for (int b_idx = 0; b_idx < 2; ++b_idx)
            expert->lut[a_idx][b_idx] =
                network_forward(expert->weights,
                                a_idx ? 1 : -1,
                                b_idx ? 1 : -1);
}

/* --- MoE inference: gate by task_id, then LUT lookup ------------------ */

static inline int moe_infer(const Expert *experts, int expert_count,
                            uint32_t task_id, int input_a, int input_b) {
    /* linear probe — with N<=16 this is one cache line, faster than a
     * branch table. For larger N, swap for a dense task_id -> index map. */
    for (int i = 0; i < expert_count; ++i)
        if (experts[i].task_id == task_id)
            return experts[i].lut[input_a > 0][input_b > 0];
    return 0;   /* task not in the pool yet: abstain */
}

/* --- checkpoint I/O (atomic: tmp + fsync + rename) -------------------- */
/* Format, little-endian fixed layout:
 *   magic        : 4 bytes  "BMMM"
 *   version      : u32      CHECKPOINT_VERSION
 *   expert_count : u32
 *   per expert:
 *       task_id  : u32
 *       weights  : u32       (9-bit value; upper bits zero)            */

static int checkpoint_save(const Expert *experts, int expert_count) {
    FILE *fp = fopen(CHECKPOINT_TMP, "wb");
    if (!fp) return 0;
    uint32_t version = CHECKPOINT_VERSION;
    uint32_t count   = (uint32_t)expert_count;
    if (fwrite(CHECKPOINT_MAGIC, 1, 4, fp) != 4)        goto fail;
    if (fwrite(&version, sizeof version, 1, fp) != 1)   goto fail;
    if (fwrite(&count,   sizeof count,   1, fp) != 1)   goto fail;
    for (int i = 0; i < expert_count; ++i) {
        if (fwrite(&experts[i].task_id, sizeof(uint32_t), 1, fp) != 1) goto fail;
        if (fwrite(&experts[i].weights, sizeof(uint32_t), 1, fp) != 1) goto fail;
    }
    fflush(fp);
    int fd = fileno(fp);
    if (fd >= 0) fsync(fd);
    fclose(fp);
    return rename(CHECKPOINT_TMP, CHECKPOINT_PATH) == 0;
fail:
    fclose(fp);
    unlink(CHECKPOINT_TMP);
    return 0;
}

static int checkpoint_load(Expert *experts, int capacity) {
    FILE *fp = fopen(CHECKPOINT_PATH, "rb");
    if (!fp) return 0;
    char     magic[4];
    uint32_t version = 0, count = 0;
    if (fread(magic, 1, 4, fp) != 4 ||
        memcmp(magic, CHECKPOINT_MAGIC, 4) != 0)             goto bad;
    if (fread(&version, sizeof version, 1, fp) != 1 ||
        version != CHECKPOINT_VERSION)                       goto bad;
    if (fread(&count, sizeof count, 1, fp) != 1 ||
        count > (uint32_t)capacity)                          goto bad;
    int loaded = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (fread(&experts[i].task_id, sizeof(uint32_t), 1, fp) != 1) break;
        if (fread(&experts[i].weights, sizeof(uint32_t), 1, fp) != 1) break;
        compile_expert(&experts[i]);
        loaded++;
    }
    fclose(fp);
    return loaded;
bad:
    fclose(fp);
    return 0;
}

/* --- helpers for the report ------------------------------------------- */

static int task_is_covered(const Expert *experts, int expert_count,
                           uint32_t task_id) {
    for (int i = 0; i < expert_count; ++i)
        if (experts[i].task_id == task_id) return 1;
    return 0;
}

static const char *task_name(uint32_t task_id) {
    switch (task_id) {
        case 0x0: return "FALSE";
        case 0x1: return "NOR";
        case 0x2: return "a AND !b";
        case 0x3: return "!b";
        case 0x4: return "!a AND b";
        case 0x5: return "!a";
        case 0x6: return "XOR";
        case 0x7: return "NAND";
        case 0x8: return "AND";
        case 0x9: return "XNOR";
        case 0xa: return "a";
        case 0xb: return "a OR !b";
        case 0xc: return "b";
        case 0xd: return "!a OR b";
        case 0xe: return "OR";
        case 0xf: return "TRUE";
        default:  return "?";
    }
}

/* --- main: grow, checkpoint, verify ----------------------------------- */

int main(void) {
    Expert experts[TASK_COUNT];
    int    expert_count = checkpoint_load(experts, TASK_COUNT);

    if (expert_count > 0)
        printf("resumed: %d experts already in %s\n", expert_count, CHECKPOINT_PATH);
    else
        printf("no checkpoint found — starting fresh\n");

    int newly_added = 0, unsolvable = 0;
    for (uint32_t task_id = 0; task_id < TASK_COUNT; ++task_id) {
        if (task_is_covered(experts, expert_count, task_id)) continue;

        uint32_t weights;
        if (!search_task_solver(task_id, &weights)) {
            printf("  task 0x%x %-12s  : no 9-bit solver exists\n",
                   task_id, task_name(task_id));
            unsolvable++;
            continue;
        }

        experts[expert_count].task_id = task_id;
        experts[expert_count].weights = weights;
        compile_expert(&experts[expert_count]);
        expert_count++;
        newly_added++;

        if (!checkpoint_save(experts, expert_count)) {
            fprintf(stderr, "FATAL: checkpoint save failed\n");
            return 1;
        }
        printf("  + task 0x%x %-12s  weights=0x%03x   saved (%d experts)\n",
               task_id, task_name(task_id), weights, expert_count);
    }

    printf("\ngrowth this run: +%d experts | total covered: %d/%d | unsolvable: %d\n",
           newly_added, expert_count, TASK_COUNT, unsolvable);

    /* exhaustive verification across every (task, input) pair */
    int checked = 0, correct = 0;
    for (uint32_t task_id = 0; task_id < TASK_COUNT; ++task_id) {
        if (!task_is_covered(experts, expert_count, task_id)) continue;
        for (int input_row = 0; input_row < 4; ++input_row) {
            int a = (input_row & 2) ? 1 : -1;
            int b = (input_row & 1) ? 1 : -1;
            int predicted = moe_infer(experts, expert_count, task_id, a, b);
            int truth     = task_truth(task_id, a, b);
            checked++;
            if (predicted == truth) correct++;
        }
    }
    printf("verification   : %d/%d correct across all covered tasks%s\n",
           correct, checked, (correct == checked) ? "  [OK]" : "  [FAIL]");

    printf("\nstate file     : %s  (delete to start over)\n", CHECKPOINT_PATH);
    return (correct == checked) ? 0 : 2;
}

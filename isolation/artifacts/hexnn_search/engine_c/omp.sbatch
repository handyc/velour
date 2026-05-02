#!/bin/bash
# HexNN class-4 hunt — OpenMP single-node sbatch template for ALICE.
#
# This is a TEMPLATE. The hexnn_hpc_submit management command (or any
# render-and-scp pipeline) fills the {placeholders} below with concrete
# values via str.format. ALICE prohibits automated sbatch — a human
# operator copies the rendered script onto the cluster and runs
# `sbatch omp.sbatch`.
#
# Why OpenMP not MPI here:
#   * The standard ALICE allocation is 1 node × 20 cores × 4 h. Single-
#     node compute means MPI's inter-rank message passing buys you
#     nothing — OpenMP shared-memory across one node is strictly faster.
#   * The MPI islands variant (mpi_islands.c + islands.sbatch) is for
#     multi-node allocations where you want >1 island.
#
# Defaults below are tuned for the standard slot:
#   --pop = ${{SLURM_CPUS_PER_TASK}}        (one genome per core)
#   --seconds 14000                          (4h - 200s margin)
#   --ckpt 25                                (resilient to wall-time kill)
#
# When run by hand, replace each <name> placeholder before submitting.

#SBATCH --job-name=hexnn-omp
#SBATCH --partition={partition}
#SBATCH --time={time_limit}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus_per_task}
#SBATCH --mem={mem}
#SBATCH --output={remote_dir}/hexnn-omp-%j.out
#SBATCH --error={remote_dir}/hexnn-omp-%j.err
{account_line}

set -euo pipefail

# Module bootstrap. ALICE has GCC ≥ 11 on basically every partition;
# the OpenMP runtime ships with libgomp so no separate module needed.
module purge
module load GCC/13.2.0 || module load GCCcore/13.2.0 || module load GCC || true

cd {remote_dir}

# OpenMP knobs:
#   OMP_NUM_THREADS        = $SLURM_CPUS_PER_TASK    (one thread per core)
#   OMP_PROC_BIND=close    (keep threads on neighbour cores → cache locality)
#   OMP_PLACES=cores       (each place is one core, not one HT)
#   OMP_DYNAMIC=false      (don't let the runtime grow/shrink the pool)
export OMP_NUM_THREADS=${{SLURM_CPUS_PER_TASK:-{cpus_per_task}}}
export OMP_PROC_BIND=close
export OMP_PLACES=cores
export OMP_DYNAMIC=false

make omp

# A 4-hour ALICE slot at 14000 s = 4 h - 200 s safety margin so the
# checkpoint write completes before SIGTERM. Shrink if your slot is
# shorter; the time budget is a soft target, not a strict cutoff.
./hexnn_omp \
    --k {K} \
    --n-log2 {n_log2} \
    --grid-w {grid_w} \
    --grid-h {grid_h} \
    --horizon {horizon} \
    --burn-in {burn_in} \
    --pop {pop} \
    --rate-q16 {rate_q16} \
    --seed {seed} \
    --seconds {seconds} \
    --ckpt {ckpt} \
    --output {output_path} \
    --verbose

echo "[done] hexnn-omp job $SLURM_JOB_ID — $SLURM_CPUS_PER_TASK threads on $SLURMD_NODENAME"
echo "       winner: {output_path}"

#!/bin/bash
# HexNN class-4 hunt — MPI islands sbatch template for ALICE.
#
# Each MPI rank = one island = one engine_t with its own population.
# Islands run their local Hunt+Refine GA between merge points; the
# merge strategy is selected at submit time (--merge ...).
#
# The hexnn_hpc_submit management command (variant=islands) renders
# this template and bundles it into a Conduit JobHandoff. ALICE
# prohibits automated sbatch, so a human operator copies the rendered
# script onto the cluster and runs `sbatch islands.sbatch`.
#
# When run by hand, replace each <name> placeholder before submitting.

#SBATCH --job-name=hexnn-islands
#SBATCH --partition={partition}
#SBATCH --time={time_limit}
#SBATCH --nodes={nodes}
#SBATCH --ntasks={ntasks}
#SBATCH --cpus-per-task={cpus_per_task}
#SBATCH --mem-per-cpu={mem_per_cpu}
#SBATCH --output={remote_dir}/hexnn-islands-%j.out
#SBATCH --error={remote_dir}/hexnn-islands-%j.err
{account_line}

set -euo pipefail

# ALICE module bootstrap. Adjust to your home environment if your
# stack is different — the islands build needs an MPI runtime + a C99
# compiler.
module purge
module load OpenMPI/4.1.6-GCC-13.2.0 || module load OpenMPI || true

cd {remote_dir}

# Build on the head node of the allocation. Sources are scp'd into
# {remote_dir} by the submit step (engine.c / engine.h / mpi_islands.c
# / Makefile). The Makefile's `mpi` target uses mpicc.
make mpi

# Run N=ntasks ranks. Each rank holds one island; the local pop
# scoring stays single-threaded — for hybrid CPU-per-island scaling
# spawn one rank per CPU and rely on Slurm to spread them across
# nodes (--nodes={nodes} above).
mpirun --mca btl_base_warn_component_unused 0 ./hexnn_islands \
    --k {K} \
    --n-log2 {n_log2} \
    --grid {grid} \
    --pop-per-island {pop_per_island} \
    --gens-per-epoch {gens_per_epoch} \
    --epochs {epochs} \
    --steps {steps} \
    --burn-in {burn_in} \
    --rate {rate} \
    --seed {seed} \
    --merge {merge_strategy} \
    --diversity-threshold {diversity_threshold} \
    --output {output_path}

echo "[done] hexnn-islands job $SLURM_JOB_ID across $SLURM_NTASKS islands"

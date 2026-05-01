#!/bin/bash
# HexNN class-4 hunt — multi-CPU sbatch template for ALICE.
#
# This is a TEMPLATE. The hexnn_hpc_submit management command fills the
# placeholders below (e.g. partition, cpus_per_task) with concrete
# values via str.format and bundles the resulting script into a
# Conduit JobHandoff. ALICE prohibits automated sbatch, so a human
# operator copies the rendered script onto the cluster, runs
# `sbatch cpu.sbatch`, and pastes the Slurm job ID back into Velour.
#
# When run by hand, replace each <name> placeholder with a sensible
# value before submitting.

#SBATCH --job-name=hexnn-hpc-cpu
#SBATCH --partition={partition}
#SBATCH --time={time_limit}
#SBATCH --nodes={nodes}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus_per_task}
#SBATCH --mem={mem}
#SBATCH --output={remote_dir}/hexnn-hpc-%j.out
#SBATCH --error={remote_dir}/hexnn-hpc-%j.err
{account_line}

set -euo pipefail

# ALICE-style module bootstrap. Adjust for your home environment if
# different — multi-CPU build only needs Python ≥ 3.10 + numpy.
module purge
module load Python/3.11.5-GCCcore-13.2.0 || true

# A user venv keeps the Python deps under your home; idempotent.
VENV="$HOME/.cache/velour-hexnn-hpc"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip
    "$VENV/bin/pip" install numpy
fi
source "$VENV/bin/activate"

cd {remote_dir}

# Run the Hunt + Refine — see cpu.py --help for params. The arguments
# below are the values picked at submit time.
python cpu.py \
    --k {K} \
    --n-log2 {n_log2} \
    --grid {grid} \
    --steps {steps} \
    --burn-in {burn_in} \
    --pop {pop} \
    --gens {gens} \
    --rate {rate} \
    --seed {seed} \
    --workers $SLURM_CPUS_PER_TASK \
    --output {output_path}

echo "[done] hexnn-hpc-cpu job $SLURM_JOB_ID on $SLURMD_NODENAME"

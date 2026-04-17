#!/bin/bash
#SBATCH --job-name=tinyllm
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4
#SBATCH --output=tinyllm-%j.log

# Adjust the module loads for your cluster. These are examples.
set -euo pipefail
module purge || true
# module load python/3.11 cuda/12.2 || true

# Prefer a project-local venv so runs are reproducible.
if [ ! -d venv ]; then
    python -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
fi

venv/bin/python train.py \
    --out       tinyllm-out \
    --steps     4000 \
    --batch     16 \
    --block     256 \
    --lr        3e-4 \
    --n_layer   4 \
    --n_embd    192 \
    --n_head    4 \
    --corpus    tinystories

echo 'training complete — convert with: bash convert.sh tinyllm-out'

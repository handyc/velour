"""train.py — train a tiny GPT-2 from scratch on TinyStories (or any corpus).

Produces a HuggingFace-format checkpoint at --out. Feed that to
`convert.sh` to emit tinyllm.gguf for llama.cpp / ollama / wllama.

Usage (local smoke test):
    pip install -r requirements.txt
    python train.py --steps 200 --batch 8 --corpus sample_corpus.txt

Usage (SLURM):
    sbatch slurm.sh

Size dials (n_embd * n_layer * n_head) set the total param count:
    n_embd=192, n_layer=4, n_head=4  -> ~11 M params (default)
    n_embd=128, n_layer=2, n_head=4  -> ~6 M  params
    n_embd=64,  n_layer=2, n_head=4  -> ~3 M  params
"""
import argparse, os, time
import torch
from transformers import GPT2Config, GPT2LMHeadModel, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out',     default='tinyllm-out')
    ap.add_argument('--steps',   type=int,   default=4000)
    ap.add_argument('--batch',   type=int,   default=16)
    ap.add_argument('--block',   type=int,   default=256)
    ap.add_argument('--lr',      type=float, default=3e-4)
    ap.add_argument('--n_layer', type=int,   default=4)
    ap.add_argument('--n_embd',  type=int,   default=192)
    ap.add_argument('--n_head',  type=int,   default=4)
    ap.add_argument('--corpus',  default='tinystories',
                    help='"tinystories" to pull from HF, or path to a text file.')
    ap.add_argument('--log_every', type=int, default=100)
    args = ap.parse_args()

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'device: {device}', flush=True)

    tok = AutoTokenizer.from_pretrained('gpt2')
    tok.pad_token = tok.eos_token

    cfg = GPT2Config(
        vocab_size=tok.vocab_size,
        n_positions=args.block,
        n_ctx=args.block,
        n_embd=args.n_embd,
        n_layer=args.n_layer,
        n_head=args.n_head,
    )
    model = GPT2LMHeadModel(cfg).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f'model params: {n_params/1e6:.2f}M', flush=True)

    if args.corpus == 'tinystories':
        from datasets import load_dataset
        ds = load_dataset('roneneldan/TinyStories', split='train[:5%]')
        texts = ds['text']
    else:
        with open(args.corpus, 'r') as f:
            texts = [f.read()]

    print('tokenizing...', flush=True)
    ids_list = []
    for txt in texts:
        ids_list.extend(tok.encode(txt))
    ids = torch.tensor(ids_list, dtype=torch.long)
    print(f'corpus tokens: {ids.numel()/1e6:.2f}M', flush=True)
    if ids.numel() < args.block + 1:
        raise SystemExit('corpus too small for block size')

    def sample_batch():
        hi = ids.numel() - args.block - 1
        idx = torch.randint(0, hi, (args.batch,))
        xb = torch.stack([ids[i:i+args.block]     for i in idx]).to(device)
        yb = torch.stack([ids[i+1:i+args.block+1] for i in idx]).to(device)
        return xb, yb

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.1,
                            betas=(0.9, 0.95))
    model.train()
    t0 = time.time()
    for step in range(args.steps):
        xb, yb = sample_batch()
        out = model(input_ids=xb, labels=yb)
        loss = out.loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        if step % args.log_every == 0:
            dt = time.time() - t0
            print(f'step {step:5d}  loss {loss.item():.4f}  '
                  f'elapsed {dt:.1f}s', flush=True)

    os.makedirs(args.out, exist_ok=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f'saved HF checkpoint to {args.out}', flush=True)
    print(f'next: bash convert.sh {args.out}', flush=True)


if __name__ == '__main__':
    main()

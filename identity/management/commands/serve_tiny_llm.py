"""Tiny OpenAI-compatible /v1/chat/completions server backed by a
HuggingFace transformers CausalLM.

For local development and Velour-side LLM-plumbing smoke tests.
Single-process, single-model, single-threaded inference — concurrent
requests serialize on `model.generate()`. No auth (binds to 127.0.0.1).

Usage:
    venv/bin/python manage.py serve_tiny_llm \\
        --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 \\
        --port 9999
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.core.management.base import BaseCommand


# Filled in by handle(); read by the request handler.
_LOCK = threading.Lock()
_TOK = None
_MODEL = None
_MODEL_NAME = ''


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path not in ('/v1/chat/completions', '/chat/completions'):
            self.send_error(404, 'unknown path')
            return
        length = int(self.headers.get('Content-Length', '0') or '0')
        try:
            body = json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            self.send_error(400, f'bad JSON: {e}')
            return

        messages = body.get('messages', [])
        max_tokens = int(body.get('max_tokens', 200))
        temperature = float(body.get('temperature', 0.7))

        import torch
        with _LOCK:
            tok, mdl = _TOK, _MODEL
            # Prefer the model's chat template when available; otherwise
            # collapse messages into a plain prompt.
            if getattr(tok, 'chat_template', None):
                # Two-step: format template to string, then tokenize.
                # `apply_chat_template(return_tensors='pt')` is a
                # BatchEncoding in transformers 5.x, not a raw tensor.
                text = tok.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
            else:
                text = ''
                for m in messages:
                    text += f"{m.get('role','user')}: {m.get('content','')}\n"
                text += 'assistant: '
            input_ids = tok(text, return_tensors='pt').input_ids
            input_len = input_ids.shape[1]

            t0 = time.monotonic()
            with torch.no_grad():
                out = mdl.generate(
                    input_ids,
                    max_new_tokens=max_tokens,
                    do_sample=temperature > 0,
                    temperature=max(temperature, 1e-5),
                    pad_token_id=tok.eos_token_id,
                )
            latency_ms = int((time.monotonic() - t0) * 1000)

            generated = out[0, input_len:]
            text = tok.decode(generated, skip_special_tokens=True)

        resp = {
            'id':      f'chatcmpl-{int(time.time())}',
            'object':  'chat.completion',
            'created': int(time.time()),
            'model':   _MODEL_NAME,
            'choices': [{
                'index': 0,
                'message': {'role': 'assistant', 'content': text},
                'finish_reason': 'stop',
            }],
            'usage': {
                'prompt_tokens':     input_len,
                'completion_tokens': int(generated.numel()),
                'total_tokens':      input_len + int(generated.numel()),
            },
            '_velour_latency_ms': latency_ms,
        }
        out_body = json.dumps(resp).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out_body)))
        self.end_headers()
        self.wfile.write(out_body)

    def log_message(self, format, *args):  # noqa: A002
        # Keep stderr clean unless we're debugging.
        return


class Command(BaseCommand):
    help = ("Start a tiny OpenAI-compatible /v1/chat/completions server "
            "backed by a HuggingFace transformers CausalLM. Local-dev only.")

    def add_arguments(self, parser):
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--port', type=int, default=9999)
        parser.add_argument('--model',
                            default='TinyLlama/TinyLlama-1.1B-Chat-v1.0',
                            help='HuggingFace model ID. Must already be in '
                                 'the local HF cache or downloadable.')

    def handle(self, *args, **opts):
        from transformers import AutoTokenizer, AutoModelForCausalLM

        global _TOK, _MODEL, _MODEL_NAME
        self.stdout.write(self.style.NOTICE(
            f'loading {opts["model"]} ...'))
        _TOK = AutoTokenizer.from_pretrained(opts['model'])
        if _TOK.pad_token_id is None:
            _TOK.pad_token = _TOK.eos_token
        _MODEL = AutoModelForCausalLM.from_pretrained(opts['model'])
        _MODEL.eval()
        _MODEL_NAME = opts['model']
        srv = ThreadingHTTPServer((opts['host'], opts['port']), _Handler)
        self.stdout.write(self.style.SUCCESS(
            f'model loaded — serving on '
            f'http://{opts["host"]}:{opts["port"]}/v1/chat/completions'))
        # The READY sentinel is emitted only after the listening socket
        # is bound, so a watcher polling for "READY" won't race the
        # accept loop.
        self.stdout.write('READY')
        self.stdout.flush()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            self.stdout.write('shutting down')
        finally:
            srv.server_close()

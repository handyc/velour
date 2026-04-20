"""Rebuild `loghi_htr.ipynb` — a Transkribus-clone Jupyter notebook that
wraps KNAW-HuC's Loghi HTR pipeline in an ipywidgets GUI.

Run from the repo root:
    venv/bin/python conduit/notebooks/build_loghi_htr.py

The resulting .ipynb is what Conduit serves from /conduit/notebooks/.
Users open it on ALICE Open OnDemand (or locally if they have
apptainer/singularity + the Loghi container). Notebook falls back to
mock PAGE-XML output when no container runtime is available, so the
rest of the flow is still exercisable without a live cluster.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / 'loghi_htr.ipynb'


def md(text: str) -> dict:
    return {
        'cell_type': 'markdown',
        'metadata': {},
        'source': text,
    }


def code(text: str, hide_input: bool = False) -> dict:
    cell = {
        'cell_type': 'code',
        'execution_count': None,
        'metadata': {},
        'outputs': [],
        'source': text,
    }
    if hide_input:
        cell['metadata']['jupyter'] = {'source_hidden': True}
    return cell


INTRO_MD = r"""# Transkribus Clone — Loghi HTR Pipeline

A Jupyter-hosted GUI for **handwritten text recognition** using
[KNAW-HuC's Loghi pipeline](https://github.com/knaw-huc/loghi).

**Workflow**

1. Upload page scans (PNG / JPG / TIFF).
2. Pick a model (language + period).
3. Run the pipeline — layout analysis, baseline detection, HTR.
4. Inspect the extracted text per page, then download the PAGE-XML bundle.

**Where this runs**

- **ALICE Open OnDemand (preferred):** the notebook runs *inside* the
  cluster, calls Loghi via `apptainer exec`, and produces PAGE-XML on
  scratch. No copy-paste job submission; no outbound data transfer.
- **Local fallback:** if no `apptainer`/`singularity` binary is
  available, the notebook writes placeholder PAGE-XML so the UI and
  result-rendering cells still execute.

Expand the Setup / Engine / Viewer cells below only if you need to tweak
the defaults — the bottom cell contains the full user interface.
"""


SETUP_CODE = r"""# --- Setup (environment + workspace) ---------------------------------
import io
import os
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

try:
    import ipywidgets as widgets
    from IPython.display import display, HTML, Image
except ImportError as exc:
    print('ipywidgets is required. On ALICE OnDemand this is pre-'
          'installed; locally: pip install ipywidgets', file=sys.stderr)
    raise

WORKSPACE = Path(os.environ.get('LOGHI_WORKSPACE',
                                Path.home() / 'loghi_workspace'))
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Container runtime. ALICE has apptainer; a few sites still ship
# singularity. Either works — the Loghi image has no runtime-specific
# bits.
CONTAINER_BIN = shutil.which('apptainer') or shutil.which('singularity')

# Path to the pre-pulled Loghi image. Override via env var on ALICE
# where scratch paths vary per user.
LOGHI_SIF = Path(os.environ.get(
    'LOGHI_SIF',
    Path.home() / 'containers' / 'loghi.sif'))

# Loghi has several published HTR models; this dropdown is a curated
# subset. Add more by extending MODELS below.
MODELS = {
    'generic-2023-02-15':        'Loghi generic (multilingual, 2023)',
    'dutch-handwriting-2023':    'Dutch handwriting (modern, 2023)',
    'early-modern-dutch-17c':    'Early-modern Dutch (17th c.)',
    'early-modern-dutch-18c':    'Early-modern Dutch (18th c.)',
    'french-handwriting':        'French handwriting (general)',
    'medieval-latin':            'Medieval Latin',
}

print(f'workspace:      {WORKSPACE}')
print(f'container bin:  {CONTAINER_BIN or "(none — will use mock output)"}')
print(f'Loghi image:    {LOGHI_SIF} '
      f'{"[found]" if LOGHI_SIF.exists() else "[not found]"}')
"""


STYLE_CODE = r"""# --- Styling (match Velour aesthetic) --------------------------------
from IPython.display import HTML
HTML('''
<style>
.transkribus-clone {
  font-family: -apple-system, system-ui, "Segoe UI", sans-serif;
  color: #c9d1d9;
}
.transkribus-clone h2 {
  font-size: 1.05rem; margin: 0 0 0.4rem;
  border-bottom: 1px solid #30363d; padding-bottom: 0.2rem;
}
.transkribus-clone .lede {
  color: #8b949e; font-size: 0.9rem; margin: 0 0 0.8rem;
}
.widget-label { min-width: 110px !important; color: #8b949e !important; }
.widget-text input, .widget-dropdown select {
  background: #0d1117 !important; color: #c9d1d9 !important;
  border: 1px solid #30363d !important;
}
.jupyter-button.mod-success {
  background: #238636 !important; border-color: #2ea043 !important;
}
.loghi-log {
  background: #161b22; border: 1px solid #21262d; border-radius: 4px;
  padding: 0.5rem 0.7rem; font-family: monospace; font-size: 0.78rem;
  color: #c9d1d9; white-space: pre-wrap;
}
.loghi-result {
  background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
  padding: 0.8rem 1rem; margin: 0.5rem 0;
}
.loghi-result h3 {
  font-size: 0.85rem; margin: 0 0 0.4rem; color: #58a6ff;
}
.loghi-line {
  padding: 0.15rem 0.4rem; border-left: 2px solid #30363d;
  font-size: 0.9rem; line-height: 1.5;
}
</style>
''')
"""


ENGINE_CODE = r"""# --- Engine (Loghi wrapper + PAGE-XML parser) ------------------------
PAGE_NS = '{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}'

VALID_EXTS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff'}


def _stage_uploads(upload_value, job_dir: Path) -> Path:
    input_dir = job_dir / 'input'
    input_dir.mkdir(parents=True, exist_ok=True)
    for item in upload_value:
        # ipywidgets.FileUpload.value is a tuple of dicts on v8+, a dict on v7.
        name    = item.get('name')    if isinstance(item, dict) else item['name']
        content = item.get('content') if isinstance(item, dict) else item['content']
        if hasattr(content, 'tobytes'):
            content = content.tobytes()
        (input_dir / name).write_bytes(content)
    return input_dir


def run_loghi(input_dir: Path, model: str, log) -> Path:
    '''Run Loghi na-pipeline on a directory of scanned pages.
    Returns the output directory holding PAGE-XML per input.'''
    output_dir = input_dir.parent / 'output'
    output_dir.mkdir(exist_ok=True)

    if CONTAINER_BIN is None or not LOGHI_SIF.exists():
        log(f'no container runtime / image found — writing mock PAGE-XML '
            f'for {len(list(input_dir.glob("*")))} files')
        _write_mock_pagexml(input_dir, output_dir, model)
        return output_dir

    cmd = [
        CONTAINER_BIN, 'exec',
        '--bind', f'{input_dir.parent}:/work',
        str(LOGHI_SIF),
        'bash', '-c',
        f'cd /work && na-pipeline.sh /work/input --model {model} '
        f'--output /work/output',
    ]
    log('$ ' + ' '.join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        log(proc.stdout.strip())
    if proc.returncode != 0:
        log(f'ERROR (exit {proc.returncode})')
        if proc.stderr:
            log(proc.stderr.strip())
    return output_dir


def _write_mock_pagexml(input_dir: Path, output_dir: Path, model: str):
    for img in input_dir.iterdir():
        if img.suffix.lower() not in VALID_EXTS:
            continue
        xml = output_dir / (img.stem + '.xml')
        xml.write_text(f'''<?xml version='1.0' encoding='UTF-8'?>
<PcGts xmlns='http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15'>
  <Metadata>
    <Creator>Loghi MOCK ({model})</Creator>
    <Created>{datetime.now().isoformat()}</Created>
  </Metadata>
  <Page imageFilename='{img.name}' imageWidth='0' imageHeight='0'>
    <TextRegion id='r1'>
      <Coords points='10,10 100,10 100,50 10,50'/>
      <TextLine id='r1_l1'>
        <Coords points='10,10 100,10 100,50 10,50'/>
        <TextEquiv><Unicode>[mock] placeholder line for {img.name}</Unicode></TextEquiv>
      </TextLine>
      <TextLine id='r1_l2'>
        <Coords points='10,55 100,55 100,90 10,90'/>
        <TextEquiv><Unicode>[mock] second placeholder line</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>
''')


def extract_lines(xml_path: Path) -> list[str]:
    tree = ET.parse(xml_path)
    out = []
    for line in tree.iter(f'{PAGE_NS}TextLine'):
        uni = line.find(f'.//{PAGE_NS}Unicode')
        if uni is not None and uni.text:
            out.append(uni.text)
    return out


def build_zip(output_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in output_dir.rglob('*'):
            if f.is_file():
                z.write(f, f.relative_to(output_dir))
    return buf.getvalue()
"""


UI_CODE = r"""# --- GUI -------------------------------------------------------------
upload = widgets.FileUpload(
    accept='.png,.jpg,.jpeg,.tif,.tiff',
    multiple=True,
    description='Upload scans',
)

model_dd = widgets.Dropdown(
    options=[(label, slug) for slug, label in MODELS.items()],
    value='generic-2023-02-15',
    description='HTR model:',
    style={'description_width': 'initial'},
)

run_btn = widgets.Button(
    description='Run Loghi pipeline',
    button_style='success',
    icon='play',
    layout=widgets.Layout(width='240px'),
)

log_out     = widgets.Output(layout=widgets.Layout(
    max_height='240px', overflow='auto',
    border='1px solid #30363d', padding='0.4rem'))
results_out = widgets.Output()

header = widgets.HTML('''
<div class='transkribus-clone'>
  <h2>Loghi HTR</h2>
  <p class='lede'>Upload scans, pick a model, run. PAGE-XML comes back per page.</p>
</div>
''')


def _log_fn(message: str):
    with log_out:
        print(message)


def _on_run(_btn):
    log_out.clear_output()
    results_out.clear_output()

    files = upload.value
    # ipywidgets v7 returns dict-of-dicts, v8 returns tuple-of-dicts.
    items = list(files.values()) if isinstance(files, dict) else list(files)
    if not items:
        _log_fn('no files uploaded — click Upload scans first.')
        return

    job_dir = WORKSPACE / f'job-{datetime.now():%Y%m%d-%H%M%S}'
    _log_fn(f'job dir: {job_dir}')
    input_dir = _stage_uploads(items, job_dir)
    _log_fn(f'staged {len(list(input_dir.iterdir()))} images → {input_dir}')
    _log_fn(f'model: {model_dd.value}')

    output_dir = run_loghi(input_dir, model_dd.value, _log_fn)
    xmls = sorted(output_dir.glob('*.xml'))
    _log_fn(f'{len(xmls)} PAGE-XML output(s) written.')

    with results_out:
        if not xmls:
            display(HTML("<p style='color:#f85149'>No PAGE-XML produced. "
                         "Check the log above.</p>"))
            return
        for xml in xmls:
            lines = extract_lines(xml)
            html = ["<div class='loghi-result'>",
                    f"<h3>{xml.name}</h3>"]
            if lines:
                for ln in lines:
                    # Escape ugly chars.
                    safe = (ln.replace('&','&amp;').replace('<','&lt;')
                              .replace('>','&gt;'))
                    html.append(f"<div class='loghi-line'>{safe}</div>")
            else:
                html.append("<div class='loghi-line' "
                            "style='color:#6e7681'>(empty page)</div>")
            html.append('</div>')
            display(HTML(''.join(html)))

        zip_bytes = build_zip(output_dir)
        zip_path = job_dir / 'loghi_output.zip'
        zip_path.write_bytes(zip_bytes)
        display(HTML(
            f"<p>Bundle: <code>{zip_path}</code> — "
            f"{len(zip_bytes)//1024} KB. On ALICE, copy out with "
            f"<code>scp</code> or your OnDemand file browser.</p>"))


run_btn.on_click(_on_run)

display(widgets.VBox([
    header,
    widgets.HBox([upload, model_dd]),
    run_btn,
    widgets.HTML("<h3 style='color:#8b949e;font-size:0.8rem;"
                 "margin:0.8rem 0 0.2rem'>Pipeline log</h3>"),
    log_out,
    widgets.HTML("<h3 style='color:#8b949e;font-size:0.8rem;"
                 "margin:0.8rem 0 0.2rem'>Results</h3>"),
    results_out,
]))
"""


CREDITS_MD = r"""## About Loghi

[Loghi](https://github.com/knaw-huc/loghi) is KNAW Humanities
Cluster's handwritten-text-recognition pipeline. Layout analysis
is handled by [Laypa](https://github.com/knaw-huc/laypa); HTR is
built on a CNN-BiLSTM architecture with CTC decoding.

**To use a real Loghi run on ALICE:**

1. `apptainer pull ~/containers/loghi.sif docker://knawhuc/loghi:latest`
   (or the version you've tested against).
2. Optionally set `LOGHI_SIF` / `LOGHI_WORKSPACE` env vars before
   launching this notebook on OnDemand.
3. If your job exceeds interactive limits, wrap the `run_loghi` call
   in an `sbatch --wait` script — the Conduit app will eventually
   auto-generate this via a `slurm_ondemand` target kind.

This notebook is produced by Velour's Conduit app. Regenerate with
`python conduit/notebooks/build_loghi_htr.py`.
"""


def build() -> dict:
    cells = [
        md(INTRO_MD),
        code(SETUP_CODE),
        code(STYLE_CODE, hide_input=True),
        code(ENGINE_CODE, hide_input=True),
        code(UI_CODE),
        md(CREDITS_MD),
    ]
    return {
        'cells': cells,
        'metadata': {
            'kernelspec': {
                'display_name': 'Python 3',
                'language':     'python',
                'name':         'python3',
            },
            'language_info': {
                'name':            'python',
                'pygments_lexer':  'ipython3',
            },
            'title': 'Transkribus Clone — Loghi HTR',
        },
        'nbformat': 4,
        'nbformat_minor': 5,
    }


if __name__ == '__main__':
    nb = build()
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False))
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes, '
          f'{len(nb["cells"])} cells)')

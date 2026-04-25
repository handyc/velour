"""Headless-browser screenshot for visually verifying ported sites.

Wraps Playwright's sync API. Used by ``manage.py browsershot`` and
by the (future) liftwp side-by-side verifier. No Django imports,
no network calls beyond fetching the URL the caller asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ShotResult:
    url: str
    out_path: Path
    width: int
    height: int
    full_page: bool
    bytes_written: int
    title: str


def shoot(
    url: str,
    out_path: Path,
    *,
    width: int = 1280,
    height: int = 800,
    full_page: bool = True,
    wait_until: str = "networkidle",
    timeout_ms: int = 15000,
) -> ShotResult:
    """Take one screenshot of ``url`` and write it to ``out_path``.

    ``wait_until``: 'load' | 'domcontentloaded' | 'networkidle' | 'commit'.
    networkidle is the safest default for static sites; for SPAs the
    caller may want to drop to 'domcontentloaded' and add a sleep.
    """
    # Local import so the module can be imported even if Playwright
    # isn't installed; the error then only surfaces when shoot() runs.
    from playwright.sync_api import sync_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport={"width": width, "height": height})
            page = ctx.new_page()
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            title = page.title() or ""
            page.screenshot(path=str(out_path), full_page=full_page)
        finally:
            browser.close()

    return ShotResult(
        url=url,
        out_path=out_path,
        width=width,
        height=height,
        full_page=full_page,
        bytes_written=out_path.stat().st_size,
        title=title,
    )

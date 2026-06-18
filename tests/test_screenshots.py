"""Browser-driven screenshot / render tests for the PM Brain dashboard view.

These render the *real* iframe page (the `_SHELL_HTML` shell plus its data + vendor routes) in
headless chromium, served by an in-process uvicorn server, then assert the dashboard, markdown
rendering, and the adjustable-layout behaviour — and drop PNGs under `artifacts/screenshots/`
for CI to upload.

Marked `screenshot` so the fast unit suite can exclude them (`pytest -m "not screenshot"`), and
skipped cleanly when Playwright or chromium isn't installed, so a plain `pytest -q` stays green
on a machine without a browser. The dedicated CI job installs the browser and runs
`pytest -m screenshot`.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("uvicorn")

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from pm import brain  # noqa: E402  (resolved via the synthetic `pm` package, see conftest)

pytestmark = pytest.mark.screenshot

_REPO = Path(__file__).resolve().parents[1]
_SHOT_DIR = Path(os.environ.get("PM_SHOT_DIR") or (_REPO / "artifacts" / "screenshots"))

# Minimal stand-ins for the host's DS plugin-kit so the iframe loads with no 404 noise (the host
# provides these at runtime; the page degrades without them, but stubbing keeps the suite clean).
_DS_KIT_JS = (
    "export function initPluginView(cb){ if(cb) cb(); }\n"
    "export function getToken(){ return ''; }\n"
    "export function apiUrl(p){ return p; }\n"
    "export function apiFetch(p,i){ return fetch(p,i); }\n"
)


def _build_app():
    from fastapi import FastAPI
    from fastapi.responses import Response
    from pm import view

    app = FastAPI()
    app.include_router(view.build_view_router(), prefix="/plugins/pm")
    app.include_router(view.build_data_router(), prefix="/api/plugins/pm")

    @app.get("/_ds/plugin-kit.css")
    def _kit_css():  # noqa: ANN202
        return Response("", media_type="text/css")

    @app.get("/_ds/plugin-kit.js")
    def _kit_js():  # noqa: ANN202
        return Response(_DS_KIT_JS, media_type="application/javascript")

    return app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _seed_brain() -> None:
    """A small, deterministic brain so every dashboard card has something to show."""
    brain.pm_brain_init.invoke({})
    brain.pm_log_decision.invoke(
        {
            "title": "Ship the weekly digest",
            "context": "Cadence fork in the road.",
            "status": "pending",
            "evidence": ["Three accounts asked  [x](../ingestion/adhoc/2026-06-15-x.md)"],
            "reverse_when": "If weekly opt-out exceeds 30% in 60 days.",
        }
    )
    brain.pm_log_decision.invoke(
        {
            "title": "Adopt provenance enforcement",
            "context": "An audit trail matters more than convenience.",
            "status": "decided",
            "evidence": ["Standard practice for evidence-based PM  (industry-knowledge)"],
        }
    )
    brain.pm_ingest.invoke(
        {
            "kind": "adhoc",
            "title": "Discovery synthesis",
            "synthesis": "## Themes\n\n- **Cadence** is the top ask\n- Users want *control*\n",
        }
    )


def _save(page, name: str) -> None:
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_SHOT_DIR / name))


@pytest.fixture(scope="session")
def browser():
    try:
        pw = sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001 — browser not installed → skip, don't fail
        pytest.skip(f"chromium not available ({exc}); run `playwright install chromium`")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def server():
    # The autouse `_isolated_brain` fixture (conftest) already pointed PM_BRAIN_DIR at a fresh
    # temp dir; seed it, then serve the app on an ephemeral port in a background thread.
    _seed_brain()
    port = _free_port()
    srv = uvicorn.Server(
        uvicorn.Config(_build_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not srv.started:
        time.sleep(0.05)
    if not srv.started:
        pytest.skip("uvicorn server did not start in time")
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1180, "height": 900})
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on(
        "console",
        lambda m: (
            errors.append(m.text)
            if (m.type == "error" and "favicon" not in m.text.lower())
            else None
        ),
    )
    pg.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
    pg.errors = errors
    yield pg
    ctx.close()


def test_dashboard_renders_all_cards(server, page):
    page.goto(f"{server}/plugins/pm/view")
    page.wait_for_selector("#cols .card", timeout=8000)
    cards = page.locator("#cols .card").count()
    assert cards >= 4
    # every card carries a drag grip + a resize handle, and the browse-everything card exists
    assert page.locator("#cols .card .cardgrip").count() == cards
    assert page.locator("#cols .card .cardresize").count() == cards
    assert page.locator('.card[data-key="files"]').count() == 1
    assert page.locator('.row[data-path="INDEX.md"]').count() == 1
    _save(page, "dashboard.png")
    assert page.errors == [], page.errors


def test_markdown_renders_and_raw_toggle(server, page):
    page.goto(f"{server}/plugins/pm/view")
    page.wait_for_selector('.row[data-path="INDEX.md"]', timeout=8000)
    page.locator('.row[data-path="INDEX.md"]').first.click()
    page.wait_for_selector("#prender", state="visible", timeout=5000)
    html = page.locator("#prender").inner_html().lower()
    assert "<table" in html or "<h1" in html  # INDEX.md has a markdown table + heading
    _save(page, "markdown_rendered.png")
    page.locator("#praw").click()  # flip to raw
    page.wait_for_selector("#pbody", state="visible", timeout=3000)
    _save(page, "markdown_raw.png")
    assert page.errors == [], page.errors


def test_layout_reorder_and_resize_persist(server, page):
    page.goto(f"{server}/plugins/pm/view")
    page.wait_for_selector("#cols .card", timeout=8000)

    # persistence round-trip: a saved order reapplies after reload
    page.evaluate(
        "localStorage.setItem('pm-brain:layout:v1', JSON.stringify("
        "{order:['areas','files','decisions']}))"
    )
    page.reload()
    page.wait_for_selector("#cols .card", timeout=8000)
    order = page.eval_on_selector_all(
        "#cols .card", "els => els.map(e => e.getAttribute('data-key'))"
    )
    assert order[0] == "areas" and order[1] == "files"

    # interactive resize of a visible card writes a column span to localStorage
    page.evaluate("localStorage.removeItem('pm-brain:layout:v1')")
    page.reload()
    page.wait_for_selector('.card[data-key="files"]', timeout=8000)
    box = page.locator('.card[data-key="files"] .cardresize').bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(box["x"] - 460, box["y"] + 20, steps=12)
    page.mouse.up()
    assert "span" in page.eval_on_selector('.card[data-key="files"]', "e => e.style.gridColumn")
    saved = page.evaluate("JSON.parse(localStorage.getItem('pm-brain:layout:v1')||'{}').spans||{}")
    assert saved.get("files")
    _save(page, "layout_adjusted.png")
    assert page.errors == [], page.errors

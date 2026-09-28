import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(tmp_path_factory) -> str:
    if url := os.environ.get("E2E_BASE_URL"):
        yield url.rstrip("/")
        return
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.exit("Build the frontend first: cd frontend && npm run build", 2)
    port = _free_port()
    env = {
        **os.environ,
        "LLM_PROVIDER": "demo",
        "DATA_DIR": str(tmp_path_factory.mktemp("data")),
        "LOG_LEVEL": "WARNING",
        "RATE_LIMIT_PER_MINUTE": "1000",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT / "backend",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/health/ready", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.exit("server did not start", 2)
    yield url
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser() -> Browser:
    with sync_playwright() as p:
        yield p.chromium.launch(executable_path=os.environ.get("E2E_CHROMIUM") or None)


@pytest.fixture
def page(browser: Browser, base_url: str) -> Page:
    context = browser.new_context(base_url=base_url, viewport={"width": 1440, "height": 900}, accept_downloads=True)
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    pg = context.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on(
        "console",
        lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None,
    )
    pg.set_default_timeout(15_000)
    yield pg
    context.close()
    assert pg.errors == [], pg.errors

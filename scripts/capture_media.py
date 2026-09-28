"""Regenerates the README screenshots and demo video from a running server.

    python scripts/capture_media.py --base http://localhost:8000 --out docs/media

Run it against a fresh data directory so only the sample dataset appears.
Needs Playwright with Chromium, and ffmpeg for the video.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSV = (
    "month,plan,signups,mrr\n2026-04,Starter,120,3600\n2026-04,Pro,45,4500\n2026-05,Starter,150,4500\n"
    "2026-05,Pro,52,5200\n2026-06,Starter,170,5100\n2026-06,Pro,61,6100\n2026-07,Starter,210,6300\n2026-07,Pro,70,7000\n"
)


class Recorder:
    def __init__(self, page: Page, folder: Path) -> None:
        self.page, self.folder, self.frames = page, folder, []

    def grab(self) -> None:
        path = self.folder / f"{len(self.frames):05d}.png"
        self.page.screenshot(path=str(path))
        self.frames.append((path, time.monotonic()))

    def hold(self, seconds: float, fps: float = 6) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.grab()
            self.page.wait_for_timeout(1000 / fps)

    def type(self, locator, text: str) -> None:
        locator.click()
        for i, ch in enumerate(text):
            locator.press_sequentially(ch)
            if i % 2 == 0:
                self.grab()

    def encode(self, out: Path) -> None:
        concat = self.folder / "frames.txt"
        stamps = [t for _, t in self.frames] + [self.frames[-1][1] + 2]
        lines = []
        for i, (path, _) in enumerate(self.frames):
            lines += [f"file '{path.name}'", f"duration {min(max(stamps[i + 1] - stamps[i], 0.04), 0.6):.3f}"]
        lines.append(f"file '{self.frames[-1][0].name}'")
        concat.write_text("\n".join(lines) + "\n")
        src = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat)]
        subprocess.run([*src, "-vf", "fps=30,scale=1440:-2,format=yuv420p", "-c:v", "libx264", "-crf", "22",
                        "-movflags", "+faststart", str(out / "demo.mp4")], check=True)
        palette = self.folder / "palette.png"
        scale = "fps=10,scale=960:-1:flags=lanczos"
        subprocess.run([*src, "-vf", f"{scale},palettegen=max_colors=160", str(palette)], check=True)
        subprocess.run([*src, "-i", str(palette), "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                        str(out / "demo.gif")], check=True)


def settle(page: Page, ms: int = 1300) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def ask(page: Page, question: str) -> None:
    page.get_by_test_id("question-input").fill(question)
    page.get_by_test_id("question-input").press("Enter")
    expect(page.get_by_test_id("result")).to_be_visible()


def demo(browser, base: str, out: Path) -> None:
    ctx = browser.new_context(base_url=base, viewport={"width": 1440, "height": 900}, color_scheme="light")
    page = ctx.new_page()
    page.goto("/")
    expect(page.get_by_test_id("welcome")).to_be_visible()
    settle(page, 400)
    with tempfile.TemporaryDirectory() as tmp:
        rec = Recorder(page, Path(tmp))
        rec.hold(1.5)
        rec.type(page.get_by_test_id("question-input"), "Revenue by month for the last 12 months")
        page.get_by_test_id("question-input").press("Enter")
        rec.hold(0.6, fps=12)
        expect(page.get_by_test_id("chart-line")).to_be_visible()
        rec.hold(3.0)
        page.get_by_test_id("view-area").click()
        rec.hold(2.0)
        page.get_by_test_id("pin").click()
        rec.hold(1.2)
        page.get_by_test_id("suggestion").filter(has_text="Top 10 products by revenue").click()
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        rec.hold(2.5)
        page.get_by_test_id("view-sql").click()
        rec.hold(2.5)
        page.get_by_test_id("pin").click()
        page.get_by_test_id("suggestion").filter(has_text="Revenue share by region").click()
        expect(page.get_by_test_id("chart-pie")).to_be_visible()
        rec.hold(2.2)
        page.get_by_test_id("pin").click()
        page.get_by_test_id("nav-dashboard").click()
        expect(page.get_by_test_id("pin-card")).to_have_count(3)
        rec.hold(3.5)
        page.keyboard.press("Control+k")
        rec.hold(0.8)
        rec.type(page.get_by_test_id("palette-input"), "profit")
        rec.hold(0.8)
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        rec.hold(2.5)
        page.get_by_test_id("theme-toggle").click()
        rec.hold(2.5)
        rec.encode(out)
    ctx.close()


def screenshots(browser, base: str, out: Path, tmp: Path) -> None:
    def shot(page: Page, name: str, full: bool = False) -> None:
        settle(page)
        page.add_style_tag(content="[data-testid=toast] { visibility: hidden !important; }")
        page.screenshot(path=str(out / f"{name}.png"), full_page=full, animations="disabled")

    ctx = browser.new_context(base_url=base, viewport={"width": 1440, "height": 900}, color_scheme="light",
                              device_scale_factor=1)
    page = ctx.new_page()
    page.add_init_script("localStorage.setItem('nl2sql.theme', 'light')")
    page.goto("/")
    expect(page.get_by_test_id("welcome")).to_be_visible()
    shot(page, "home")
    ask(page, "Revenue by month for the last 12 months")
    expect(page.get_by_test_id("chart-line")).to_be_visible()
    shot(page, "answer-line")
    page.get_by_test_id("pin").click()
    ask(page, "Top 10 products by revenue")
    page.get_by_test_id("pin").click()
    page.get_by_test_id("view-sql").click()
    shot(page, "sql-view")
    ask(page, "Revenue share by region")
    page.get_by_test_id("pin").click()
    ask(page, "Total revenue this year")
    page.get_by_test_id("pin").click()
    page.get_by_test_id("nav-dashboard").click()
    expect(page.get_by_test_id("pin-card")).to_have_count(4)
    page.wait_for_timeout(1500)
    shot(page, "dashboard", full=True)
    page.get_by_test_id("nav-ask").click()
    page.keyboard.press("Control+k")
    page.get_by_test_id("palette-input").fill("rev")
    shot(page, "command-palette")
    page.keyboard.press("Escape")
    csv = tmp / "saas_metrics.csv"
    csv.write_text(CSV)
    page.get_by_test_id("open-upload").click()
    page.get_by_test_id("upload-input").set_input_files(str(csv))
    shot(page, "upload")
    page.get_by_test_id("upload-submit").click()
    expect(page.get_by_test_id("table-saas_metrics")).to_be_visible()
    page.get_by_test_id("preview-saas_metrics").click()
    expect(page.get_by_test_id("results-table")).to_be_visible()
    shot(page, "uploaded-dataset")
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("delete-dataset").click()
    expect(page.get_by_test_id("dataset-select")).to_have_value("ecommerce")
    page.get_by_test_id("theme-toggle").click()
    ask(page, "Average order value by channel")
    expect(page.get_by_test_id("chart-bar")).to_be_visible()
    page.get_by_test_id("measures").get_by_role("button", name="Orders").click()
    shot(page, "answer-dark")
    ctx.close()

    ctx = browser.new_context(base_url=base, viewport={"width": 390, "height": 844}, device_scale_factor=2,
                              is_mobile=True, has_touch=True, color_scheme="light")
    page = ctx.new_page()
    page.add_init_script("localStorage.setItem('nl2sql.theme', 'light')")
    page.goto("/")
    page.get_by_test_id("suggestion").filter(has_text="Revenue share by region").tap()
    expect(page.get_by_test_id("chart-pie")).to_be_visible()
    shot(page, "mobile")
    ctx.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/media")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        if shutil.which("ffmpeg"):
            demo(browser, args.base, out)
        screenshots(browser, args.base, out, Path(tmp))
        browser.close()
    print("media written to", out)


if __name__ == "__main__":
    main()

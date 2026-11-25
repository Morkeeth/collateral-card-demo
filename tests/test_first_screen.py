"""A judge's first 30 seconds: without scrolling, a fresh visitor sees the problem,
the agent's spend request and the desk's CUT decision, at desktop and phone width.

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`).
Skips when Playwright is missing. Serves this folder on a free loopback port.
"""
import json
import socket
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

VIEWPORTS = {"desktop": (1280, 800), "phone": (390, 844)}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class FirstScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        cls.server = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=str(ROOT)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}/"
        cls.receipt = json.loads((ROOT / "demo/desk.json").read_text())
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def first_screen(self, width, height):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(self.url, wait_until="networkidle")
        page.wait_for_selector("#desk-result:not([hidden])", timeout=5000)
        boxes = page.evaluate(
            """() => Object.fromEntries(['problem', 'agent-request', 'decision'].map(id => {
                const el = document.querySelector(`[data-testid=${id}]`);
                if (!el) return [id, null];
                const b = el.getBoundingClientRect();
                return [id, {top: b.top, bottom: b.bottom, visible: el.offsetParent !== null, text: el.innerText}];
            }))"""
        )
        page.close()
        return boxes

    def test_problem_request_and_cut_fit_the_first_screen(self):
        check = next(c for c in self.receipt["checks"] if c["action"] == "CUT")
        for name, (w, h) in VIEWPORTS.items():
            with self.subTest(viewport=name):
                boxes = self.first_screen(w, h)
                for part in ("problem", "agent-request", "decision"):
                    box = boxes[part]
                    self.assertIsNotNone(box, f"{name}: no [data-testid={part}] on the page")
                    self.assertTrue(box["visible"], f"{name}: {part} is hidden")
                    self.assertGreaterEqual(box["top"], 0, f"{name}: {part} starts above the screen")
                    self.assertLessEqual(box["bottom"], h, f"{name}: {part} ends at {box['bottom']:.0f}px, below the {h}px screen")
                self.assertIn("Friday", boxes["problem"]["text"])
                self.assertIn("$40.00", boxes["agent-request"]["text"])
                decision = boxes["decision"]["text"]
                self.assertIn("Cut", decision)
                # The figure comes from the receipt, not from the page source.
                self.assertIn(f"${check['allowed_usd']}", decision)


if __name__ == "__main__":
    unittest.main()

"""A judge's first 30 seconds: without scrolling, a fresh visitor sees the problem,
the agent's spend request, the lender's answer and the desk's CUT decision.

Screen heights are what a browser leaves for the page, not the bare display:
about 720 px on a 1280 px laptop and about 660 px in phone Safari at 390 px.

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`).
Skips when either is missing. Serves this folder on a free loopback port.
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

VIEWPORTS = {"laptop": (1280, 720), "phone": (390, 660)}
PARTS = ("problem", "agent-request", "lender-answer", "decision")


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
        try:
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception as exc:  # Chromium binary not installed
            cls.pw.stop()
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest(f"Chromium is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def first_screen(self, width, height, receipt=None):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        if receipt is not None:
            body = json.dumps(receipt)
            page.route("**/demo/desk.json", lambda route: route.fulfill(status=200, content_type="application/json", body=body))
        page.goto(self.url, wait_until="networkidle")
        page.wait_for_selector("#desk-result:not([hidden])", timeout=5000)
        page.evaluate("document.fonts.ready")
        boxes = page.evaluate(
            """(parts) => Object.fromEntries(parts.map(id => {
                const el = document.querySelector(`[data-testid=${id}]`);
                if (!el) return [id, null];
                const b = el.getBoundingClientRect();
                return [id, {top: b.top, bottom: b.bottom, visible: el.offsetParent !== null, text: el.innerText}];
            }))""",
            list(PARTS),
        )
        page.close()
        return boxes

    def assert_first_screen(self, name, h, boxes):
        for part in PARTS:
            box = boxes[part]
            self.assertIsNotNone(box, f"{name}: no [data-testid={part}] on the page")
            self.assertTrue(box["visible"], f"{name}: {part} is hidden")
            self.assertGreaterEqual(box["top"], 0, f"{name}: {part} starts above the screen")
            self.assertLessEqual(box["bottom"], h, f"{name}: {part} ends at {box['bottom']:.0f}px, below the {h}px screen")

    def test_problem_request_and_cut_fit_the_first_screen(self):
        check = next(c for c in self.receipt["checks"] if c["action"] == "CUT")
        lender = self.receipt["desk"]["spend"]["lender_would_allow_usd"]
        for name, (w, h) in VIEWPORTS.items():
            with self.subTest(viewport=name):
                boxes = self.first_screen(w, h)
                self.assert_first_screen(name, h, boxes)
                self.assertIn("Friday", boxes["problem"]["text"])
                self.assertIn(f"${check['amount_usd']}", boxes["agent-request"]["text"])
                self.assertIn(f"${lender}", boxes["lender-answer"]["text"])
                self.assertIn("Cut", boxes["decision"]["text"])
                self.assertIn(f"${check['allowed_usd']}", boxes["decision"]["text"])

    def test_first_screen_figures_come_from_the_receipt(self):
        changed = json.loads(json.dumps(self.receipt))
        cut = next(c for c in changed["checks"] if c["action"] == "CUT")
        cut["amount_usd"], cut["allowed_usd"] = "41.00", "12.34"
        changed["desk"]["spend"]["lender_would_allow_usd"] = "99.99"
        w, h = VIEWPORTS["phone"]
        boxes = self.first_screen(w, h, receipt=changed)
        self.assert_first_screen("phone, changed receipt", h, boxes)
        self.assertIn("$41.00", boxes["agent-request"]["text"])
        self.assertIn("$99.99", boxes["lender-answer"]["text"])
        self.assertIn("$12.34", boxes["decision"]["text"])
        self.assertNotIn("26.31", boxes["decision"]["text"])


if __name__ == "__main__":
    unittest.main()

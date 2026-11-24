"""Stock Desk for agents: print or serve the desk for the saved 6 November NVDAc weekend.

    python3 -B proof/run_desk.py --out demo/desk.json      # write the browser receipt
    python3 -B proof/run_desk.py --serve 8851              # loopback HTTP for an agent

Endpoints when serving (loopback only):
    GET /desk                 positions, exposure, health in both views, limits, safe spend
    GET /desk/spend?usd=25    ALLOW, REPAY_FIRST or REFUSE for one spend funded by borrowing
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collateral_card.desk import DEMO_BOOK, DEMO_LIMITS, after_reopen, check_spend, view

WEEKEND = "2026-11-06"
AS_OF = "2026-11-09T00:05:00Z"
STORY_SPENDS = ("5.00", "25.00", "60.00")


def receipt():
    return {
        "desk": view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF),
        "checks": [check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, usd) for usd in STORY_SPENDS],
        "after_reopen": after_reopen(DEMO_BOOK, DEMO_LIMITS, WEEKEND, "25.00"),
        "labels": ["historical replay", "demo book, not a real wallet", "no trades are placed"],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, status, body):
        raw = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/desk":
                return self._send(200, view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF))
            if url.path == "/desk/spend":
                usd = parse_qs(url.query).get("usd", [""])[0]
                return self._send(200, check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, usd))
        except ValueError as error:
            return self._send(400, {"error": str(error)})
        self._send(404, {"error": "Use /desk or /desk/spend?usd=AMOUNT."})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", args.serve), Handler)
        print(f"Stock Desk on http://127.0.0.1:{args.serve}/desk", flush=True)
        server.serve_forever()
    body = json.dumps(receipt(), indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
    else:
        print(body, end="")


if __name__ == "__main__":
    main()

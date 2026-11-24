import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest import TestCase, skipUnless

ROOT = Path(__file__).resolve().parents[1]


@skipUnless(os.environ.get("CHECK_BASE_SEPOLIA_FORK") == "1", "run with the Base Sepolia fork")
class SepoliaJourneyTest(TestCase):
    def test_paid_quote_settles_and_single_use_authorization_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence.json"
            subprocess.run(
                [sys.executable, "-B", str(ROOT / "proof/run_sepolia.py"), "--out", str(output)],
                check=True, timeout=90,
            )
            receipt = json.loads(output.read_text())
        self.assertEqual(receipt["mode"], "local Base Sepolia fork")
        self.assertEqual(receipt["network"], "eip155:84532")
        self.assertEqual(receipt["token"], "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
        self.assertEqual(receipt["http"], {"challenge": 402, "paid": 200, "retry": 402})
        self.assertEqual(receipt["buyer_delta_raw"], -50000)
        self.assertEqual(receipt["seller_delta_raw"], 50000)
        self.assertEqual(receipt["retry_delta_raw"], 0)
        self.assertEqual(receipt["remote_writes"], 0)
        self.assertEqual(receipt["quote"]["pool_minus_lending_percent"], "-5.05")
        self.assertTrue(re.fullmatch(r"0x[0-9a-f]{64}", receipt["local_settlement_tx"]))

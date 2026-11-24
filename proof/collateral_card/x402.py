"""x402 v2, exact scheme on EVM with EIP-3009 (standard library only).

Shapes follow coinbase/x402 specs/schemes/exact/scheme_exact_evm.md and specs/transports-v2/http.md,
read 21 Nov 2026.
"""
import base64
import json
import re

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
NETWORK = "eip155:8453"
VERSION = 2
HEADER_REQUIRED = "PAYMENT-REQUIRED"
HEADER_SIGNATURE = "PAYMENT-SIGNATURE"
HEADER_RESPONSE = "PAYMENT-RESPONSE"
# EIP-712 domain of the USDC contract on Base.
TOKEN_NAME = "USD Coin"
TOKEN_VERSION = "2"


def requirements(
    pay_to, amount_raw, max_timeout_seconds=60, *,
    network=NETWORK, asset=USDC, token_name=TOKEN_NAME,
):
    return {
        "scheme": "exact",
        "network": network,
        "amount": str(int(amount_raw)),
        "asset": asset,
        "payTo": pay_to,
        "maxTimeoutSeconds": int(max_timeout_seconds),
        "extra": {"name": token_name, "version": TOKEN_VERSION},
    }


def payment_required(terms, url):
    return {
        "x402Version": VERSION,
        "error": f"{HEADER_SIGNATURE} header is required",
        "resource": {"url": url, "description": "Recorded Base weekend price comparison", "mimeType": "application/json"},
        "accepts": [terms],
    }


def encode_header(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return base64.b64encode(raw).decode()


def decode_header(header: str) -> dict:
    try:
        obj = json.loads(base64.b64decode(header, validate=True).decode())
    except Exception as e:
        raise ValueError("not base64 json") from e
    if not isinstance(obj, dict):
        raise ValueError("not base64 json")
    return obj


def _same(a, b):
    return str(a or "").lower() == str(b or "").lower()


def _hex_value(value, digits):
    return isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{%d}" % digits, value)


def check_payment(payment, terms, now):
    """Check a PaymentPayload against our own terms. The token contract checks the signature at settlement."""
    if payment.get("x402Version") != VERSION:
        return False, "wrong version"
    accepted = payment.get("accepted")
    payload = payment.get("payload")
    if not isinstance(accepted, dict) or not isinstance(payload, dict):
        return False, "invalid payload"
    if accepted.get("scheme") != terms["scheme"]:
        return False, "wrong scheme"
    if accepted.get("network") != terms["network"]:
        return False, "wrong network"
    if not _same(accepted.get("asset"), terms["asset"]):
        return False, "wrong asset"
    if str(accepted.get("amount")) != terms["amount"]:
        return False, "wrong amount"
    if not _same(accepted.get("payTo"), terms["payTo"]):
        return False, "wrong payee"
    extra = accepted.get("extra")
    if not isinstance(extra, dict):
        return False, "wrong token domain"
    if extra.get("name") != terms["extra"]["name"] or extra.get("version") != terms["extra"]["version"]:
        return False, "wrong token domain"
    auth = payload.get("authorization")
    if not isinstance(auth, dict):
        return False, "invalid authorization"
    if not _hex_value(auth.get("from"), 40) or not _hex_value(auth.get("nonce"), 64):
        return False, "invalid authorization"
    if not _hex_value(payload.get("signature"), 130):
        return False, "invalid signature"
    if not _same(auth.get("to"), terms["payTo"]):
        return False, "wrong payee"
    if str(auth.get("value")) != terms["amount"]:
        return False, "wrong amount"
    try:
        valid_after = int(auth.get("validAfter"))
        valid_before = int(auth.get("validBefore"))
    except (TypeError, ValueError):
        return False, "bad window"
    if now >= valid_before:
        return False, "expired"
    if now <= valid_after:
        return False, "not yet valid"
    if valid_before > now + terms["maxTimeoutSeconds"]:
        return False, "window exceeds timeout"
    return True, "ok"

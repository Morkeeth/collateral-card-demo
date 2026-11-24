"""Stock Desk: one agent's stock positions, exposure and spending limits on Base.

The desk prices every position twice. The lender view uses the frozen Aave price, which is
what the lending market believes over a weekend. The weekend view uses the closed Base pool
candle minus the in-sample error band. Every spend is checked against the owner's limits in
the weekend view. The desk never buys or sells stock. It can only allow a spend, ask for a
repayment first, or refuse.
"""
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP

from .paid_quote import OBSERVATIONS, weekend_quote

BAND_PTS = Decimal("0.71")  # proof/inputs.json band_pts, the in-sample forecast error band
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Book:
    positions: tuple  # ((stock, units), ...)
    debt_usd: str  # USDC borrowed against the stocks
    cash_usd: str  # USDC the agent holds
    spent_this_week_usd: str


@dataclass(frozen=True)
class Limits:
    min_health: str = "1.30"
    max_stock_share: str = "0.50"
    weekly_spend_cap_usd: str = "50.00"
    collateral_factor: str = "0.70"


DEMO_BOOK = Book(
    positions=(("NVDAc", "2"), ("TSLAc", "0.5"), ("AAPLc", "0.5")),
    debt_usd="360.00",
    cash_usd="10.00",
    spent_this_week_usd="0",
)
DEMO_LIMITS = Limits()


def _d(value, name):
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{name} must be a number.") from None
    if not out.is_finite():
        raise ValueError(f"{name} must be a number.")
    return out


def _usd(x, rounding=ROUND_HALF_EVEN):
    return str(x.quantize(CENT, rounding=rounding))


def _hf(x):
    return str(x.quantize(Decimal("0.001"), rounding=ROUND_DOWN))


def _health(borrow_power, debt):
    return borrow_power / debt if debt > 0 else Decimal("Infinity")


def _price(book, limits, weekend, as_of_utc):
    cf = _d(limits.collateral_factor, "collateral_factor")
    rows, lender, weekend_value = [], Decimal(0), Decimal(0)
    market_total = Decimal(0)
    for stock, units in book.positions:
        units = _d(units, "units")
        if units <= 0:
            raise ValueError("Position units must be positive.")
        q = weekend_quote(stock, weekend, as_of_utc)
        lp, mp = Decimal(q["lending_price_usd"]), Decimal(q["pool_close_usd"])
        gap = Decimal(q["pool_minus_lending_percent"])
        stressed = lp * units * (1 + (gap - BAND_PTS) / 100)
        rows.append({
            "stock": stock,
            "units": str(units),
            "lending_price_usd": q["lending_price_usd"],
            "lending_price_at_utc": q["lending_price_at_utc"],
            "pool_close_usd": q["pool_close_usd"],
            "pool_close_at_utc": q["pool_close_at_utc"],
            "gap_percent": q["pool_minus_lending_percent"],
            "lending_value_usd": _usd(lp * units),
            "market_value_usd": _usd(mp * units),
            "_market": mp * units,
        })
        lender += lp * units
        market_total += mp * units
        weekend_value += stressed
    return rows, lender * cf, weekend_value * cf, market_total


def view(book, limits, weekend, as_of_utc):
    rows, lender_power, weekend_power, market_total = _price(book, limits, weekend, as_of_utc)
    debt = _d(book.debt_usd, "debt_usd")
    floor = _d(limits.min_health, "min_health")
    cap_share = _d(limits.max_stock_share, "max_stock_share")
    breaches = []
    for r in rows:
        share = r.pop("_market") / market_total
        r["share_percent"] = str((share * 100).quantize(Decimal("0.1")))
        if share > cap_share:
            breaches.append({"stock": r["stock"], "limit": "max_stock_share",
                             "share_percent": r["share_percent"],
                             "limit_percent": str((cap_share * 100).quantize(Decimal("0.1"))),
                             "effect": "Add no more of this stock."})
    largest = max(rows, key=lambda r: Decimal(r["share_percent"]))
    weekend_hf = _health(weekend_power, debt)
    if weekend_hf < floor:
        breaches.append({"limit": "min_health", "health": _hf(weekend_hf),
                         "effect": "Repay before any new spend."})
    cash = _d(book.cash_usd, "cash_usd")
    safe = cash + max(Decimal(0), weekend_power / floor - debt).quantize(CENT, rounding=ROUND_DOWN)
    lender_safe = cash + max(Decimal(0), lender_power / floor - debt).quantize(CENT, rounding=ROUND_DOWN)
    cap_left = max(Decimal(0), _d(limits.weekly_spend_cap_usd, "cap")
                   - _d(book.spent_this_week_usd, "spent"))
    return {
        "mode": "historical replay",
        "network": "Base",
        "weekend_friday": weekend,
        "as_of_utc": as_of_utc,
        "positions": rows,
        "debt_usd": _usd(debt),
        "cash_usd": _usd(_d(book.cash_usd, "cash_usd")),
        "health": {"lender_view": _hf(_health(lender_power, debt)),
                   "weekend_view": _hf(weekend_hf),
                   "floor": limits.min_health},
        "exposure": {"largest_stock": largest["stock"],
                     "largest_share_percent": largest["share_percent"],
                     "market_value_usd": _usd(market_total)},
        "breaches": breaches,
        "spend": {"safe_now_usd": _usd(min(safe, cap_left), ROUND_DOWN),
                  "lender_would_allow_usd": _usd(min(lender_safe, cap_left), ROUND_DOWN),
                  "weekly_cap_left_usd": _usd(cap_left)},
        "limits": {"min_health": limits.min_health, "max_stock_share": limits.max_stock_share,
                   "weekly_spend_cap_usd": limits.weekly_spend_cap_usd,
                   "collateral_factor": limits.collateral_factor,
                   "error_band_points": str(BAND_PTS)},
    }


def check_spend(book, limits, weekend, as_of_utc, amount_usd):
    """Decide one spend. Cash pays first; the rest is borrowed against the stocks."""
    amount = _d(amount_usd, "amount_usd")
    if amount <= 0:
        raise ValueError("amount_usd must be positive.")
    desk = view(book, limits, weekend, as_of_utc)
    _, lender_power, weekend_power, _ = _price(book, limits, weekend, as_of_utc)
    debt = _d(book.debt_usd, "debt_usd")
    cash = _d(book.cash_usd, "cash_usd")
    floor = _d(limits.min_health, "min_health")
    cap_left = Decimal(desk["spend"]["weekly_cap_left_usd"])
    borrow = max(Decimal(0), amount - cash)
    lender_ok = _health(lender_power, debt + borrow) >= floor
    base = {"amount_usd": _usd(amount), "from_cash_usd": _usd(amount - borrow),
            "borrow_usd": _usd(borrow), "lender_would_allow": lender_ok,
            "health_now": desk["health"], "as_of_utc": as_of_utc}
    if amount > cap_left:
        return {**base, "action": "REFUSE",
                "reason": f"Over the weekly spend cap. {_usd(cap_left)} USDC left this week."}
    if _health(weekend_power, debt) < floor:
        return {**base, "action": "REFUSE",
                "reason": "Weekend health is already under the floor. Repay before any new spend."}
    if _health(weekend_power, debt + borrow) >= floor:
        return {**base, "action": "ALLOW", "reason": "Weekend health stays above the floor.",
                "health_after": _hf(_health(weekend_power, debt + borrow))}
    safe_borrow = max(Decimal(0), weekend_power / floor - debt).quantize(CENT, rounding=ROUND_DOWN)
    safe_total = min(cash + safe_borrow, cap_left)
    if safe_total <= 0:
        return {**base, "action": "REFUSE", "reason": "No safe amount left this weekend."}
    reason = ("Friday's lending price allows this spend. The weekend price does not. "
              if lender_ok else "Both prices put this spend under the floor. ")
    return {**base, "action": "CUT", "allowed_usd": _usd(safe_total),
            "reason": reason + f"Spend at most {_usd(safe_total)} USDC now.",
            "health_after": _hf(_health(weekend_power, debt + safe_total - cash))}


def after_reopen(book, limits, weekend, amount_usd):
    """Lender health once the Aave feed reopened: the full spend versus the desk's answer."""
    cf = _d(limits.collateral_factor, "collateral_factor")
    reopen = {}
    with OBSERVATIONS.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["weekend_friday"] == weekend and row["pool"] == "main":
                reopen[row["symbol"]] = (Decimal(row["reopen_usd"]), int(row["reopen_updated_at_unix"]))
    power = sum(reopen[s][0] * _d(u, "units") for s, u in book.positions) * cf
    debt = _d(book.debt_usd, "debt_usd")
    cash = _d(book.cash_usd, "cash_usd")
    decision = check_spend(book, limits, weekend, "2026-11-09T00:05:00Z", amount_usd)
    spent = _d(decision.get("allowed_usd", decision["amount_usd"]), "allowed")
    if decision["action"] == "REFUSE":
        spent = Decimal(0)
    full_debt = debt + max(Decimal(0), _d(amount_usd, "amount_usd") - cash)
    desk_debt = debt + max(Decimal(0), spent - cash)
    without_hf, with_hf = _health(power, full_debt), _health(power, desk_debt)
    floor = _d(limits.min_health, "min_health")
    return {
        "reopen_at_unix": max(reopen[s][1] for s, _ in book.positions),
        "requested_usd": _usd(_d(amount_usd, "amount_usd")),
        "without_desk": {"debt_usd": _usd(full_debt), "health": _hf(without_hf)},
        "with_desk": {"debt_usd": _usd(desk_debt), "health": _hf(with_hf), "spent_usd": _usd(spent)},
        "floor": limits.min_health,
        "floor_breached_without_desk": without_hf < floor,
        "floor_breached_with_desk": with_hf < floor,
    }

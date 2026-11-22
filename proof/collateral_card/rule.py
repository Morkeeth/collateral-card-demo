"""Repay rule and fixture-weekend replay. Pure math, no chain."""

CF_DEFAULT = 0.70


def decide(
    collateral_usd,
    debt_usd,
    cf,
    predicted_pct,
    band_pts,
    trigger=1.0,
    target=1.05,
    wallet_usd=float("inf"),
):
    stress_pct = predicted_pct - band_pts
    if debt_usd <= 0:
        return {
            "action": "HOLD",
            "stress_pct": stress_pct,
            "projected_hf": float("inf"),
            "repay_usd": 0,
            "post_hf": float("inf"),
            "capped": False,
        }
    projected_hf = collateral_usd * (1 + stress_pct / 100) * cf / debt_usd
    if projected_hf >= trigger:
        return {
            "action": "HOLD",
            "stress_pct": stress_pct,
            "projected_hf": projected_hf,
            "repay_usd": 0,
            "post_hf": projected_hf,
            "capped": False,
        }
    coll_stressed = collateral_usd * (1 + stress_pct / 100)
    target_debt = coll_stressed * cf / target
    repay_usd = max(0.0, debt_usd - target_debt)
    capped = False
    if repay_usd > wallet_usd:
        repay_usd = float(wallet_usd)
        capped = True
    new_debt = debt_usd - repay_usd
    post_hf = (coll_stressed * cf / new_debt) if new_debt > 0 else float("inf")
    return {
        "action": "REPAY",
        "stress_pct": stress_pct,
        "projected_hf": projected_hf,
        "repay_usd": repay_usd,
        "post_hf": post_hf,
        "capped": capped,
    }


def replay_weekends(rows, start_hf, band_pts, cf=CF_DEFAULT):
    n = 0
    control_liquidated = 0
    saved = 0
    missed = 0
    repaid_weekends = 0
    unneeded_repays = 0
    for row in rows:
        n += 1
        debt = 1.0
        collateral = start_hf * debt / cf
        jump = row["jump_pct"]
        ctrl = start_hf * (1 + jump / 100) < 1
        decision = decide(collateral, debt, cf, row["predicted_pct"], band_pts)
        repaid = decision["action"] == "REPAY"
        if repaid:
            new_debt = debt - decision["repay_usd"]
            post_actual = (
                collateral * (1 + jump / 100) * cf / new_debt if new_debt > 0 else float("inf")
            )
        else:
            post_actual = start_hf * (1 + jump / 100)
        survives = post_actual >= 1
        if ctrl:
            control_liquidated += 1
        if repaid:
            repaid_weekends += 1
        if ctrl and survives:
            saved += 1
        if ctrl and not survives:
            missed += 1
        if repaid and not ctrl:
            unneeded_repays += 1
    return {
        "n": n,
        "control_liquidated": control_liquidated,
        "saved": saved,
        "missed": missed,
        "repaid_weekends": repaid_weekends,
        "unneeded_repays": unneeded_repays,
    }

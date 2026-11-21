/** Pure repay-rule math. Browser: window.Engine. Node: module.exports. */
(function (root) {
  "use strict";

  var CF_DEFAULT = 0.7;

  function decide(collateral_usd, debt_usd, cf, predicted_pct, band_pts, trigger, target, wallet_usd) {
    if (trigger === undefined) trigger = 1.0;
    if (target === undefined) target = 1.05;
    if (wallet_usd === undefined) wallet_usd = Infinity;
    var stress_pct = predicted_pct - band_pts;
    if (debt_usd <= 0) {
      return {
        action: "HOLD",
        stress_pct: stress_pct,
        projected_hf: Infinity,
        repay_usd: 0,
        post_hf: Infinity,
        capped: false,
      };
    }
    var projected_hf = (collateral_usd * (1 + stress_pct / 100) * cf) / debt_usd;
    if (projected_hf >= trigger) {
      return {
        action: "HOLD",
        stress_pct: stress_pct,
        projected_hf: projected_hf,
        repay_usd: 0,
        post_hf: projected_hf,
        capped: false,
      };
    }
    var coll_stressed = collateral_usd * (1 + stress_pct / 100);
    var target_debt = (coll_stressed * cf) / target;
    var repay_usd = Math.max(0.0, debt_usd - target_debt);
    var capped = false;
    if (repay_usd > wallet_usd) {
      repay_usd = Number(wallet_usd);
      capped = true;
    }
    var new_debt = debt_usd - repay_usd;
    var post_hf = new_debt > 0 ? (coll_stressed * cf) / new_debt : Infinity;
    return {
      action: "REPAY",
      stress_pct: stress_pct,
      projected_hf: projected_hf,
      repay_usd: repay_usd,
      post_hf: post_hf,
      capped: capped,
    };
  }

  function replay_weekends(rows, start_hf, band_pts, cf) {
    if (cf === undefined) cf = CF_DEFAULT;
    var n = 0;
    var control_liquidated = 0;
    var saved = 0;
    var missed = 0;
    var repaid_weekends = 0;
    var unneeded_repays = 0;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      n += 1;
      var debt = 1.0;
      var collateral = (start_hf * debt) / cf;
      var jump = row.jump_pct;
      var ctrl = start_hf * (1 + jump / 100) < 1;
      var decision = decide(collateral, debt, cf, row.predicted_pct, band_pts);
      var repaid = decision.action === "REPAY";
      var post_actual;
      if (repaid) {
        var new_debt = debt - decision.repay_usd;
        post_actual =
          new_debt > 0
            ? (collateral * (1 + jump / 100) * cf) / new_debt
            : Infinity;
      } else {
        post_actual = start_hf * (1 + jump / 100);
      }
      var survives = post_actual >= 1;
      if (ctrl) control_liquidated += 1;
      if (repaid) repaid_weekends += 1;
      if (ctrl && survives) saved += 1;
      if (ctrl && !survives) missed += 1;
      if (repaid && !ctrl) unneeded_repays += 1;
    }
    return {
      n: n,
      control_liquidated: control_liquidated,
      saved: saved,
      missed: missed,
      repaid_weekends: repaid_weekends,
      unneeded_repays: unneeded_repays,
    };
  }

  function debtFrom(row, h, cf) {
    return Math.floor(((2 * row.frozen * cf) / h) * 1e6) / 1e6;
  }

  function simulate(row, h, band, cf) {
    var debt_usd = debtFrom(row, h, cf);
    var d = decide(h / cf, 1.0, cf, row.predicted_pct, band);
    var flags = replay_weekends([row], h, band, cf);
    var repaid = d.action === "REPAY";
    var control_hf = h * (1 + row.jump_pct / 100);
    var guarded_hf = repaid
      ? ((h / cf) * (1 + row.jump_pct / 100) * cf) / (1 - d.repay_usd)
      : control_hf;
    return {
      action: d.action,
      stress_pct: d.stress_pct,
      projected_hf: d.projected_hf,
      repay_usd: d.repay_usd * debt_usd,
      control_hf: control_hf,
      guarded_hf: guarded_hf,
      control_liquidated: flags.control_liquidated === 1,
      guarded_survives: guarded_hf >= 1,
    };
  }

  function summarize(rows, h, band, cf) {
    return replay_weekends(rows, h, band, cf);
  }

  var api = {
    decide: decide,
    replay_weekends: replay_weekends,
    simulate: simulate,
    summarize: summarize,
    CF_DEFAULT: CF_DEFAULT,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.Engine = api;
})(typeof window !== "undefined" ? window : globalThis);

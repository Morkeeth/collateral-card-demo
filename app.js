(function () {
  "use strict";

  var data = window.JUDGE_DATA;
  var Engine = window.Engine;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var RECEIPT_KEY = "NVDAc|2026-11-06";
  var FONT = "Bricolage Grotesque, sans-serif";
  var MONO = "IBM Plex Mono, monospace";
  var PAD = { l: 52, r: 12, t: 22, mid: 16, b: 28 };
  var LABEL_STEP = 13;
  var animFrame = null;
  var chartGeom = null;
  var lastDraw = null;
  var reduced =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(tid) {
    return document.querySelector('[data-testid="' + tid + '"]');
  }

  function fmt2(n) {
    return Number(n).toFixed(2);
  }

  function fmt4(n) {
    return Number(n).toFixed(4);
  }

  function labelRow(row) {
    var parts = row.weekend_friday.split("-");
    var day = parseInt(parts[2], 10);
    var month = MONTHS[parseInt(parts[1], 10) - 1];
    return row.symbol + ", " + day + " " + month;
  }

  function rowKey(row) {
    return row.symbol + "|" + row.weekend_friday;
  }

  function findRow(key) {
    for (var i = 0; i < data.rows.length; i++) {
      if (rowKey(data.rows[i]) === key) return data.rows[i];
    }
    return data.rows[0];
  }

  function friUnix(row) {
    var fri = row.weekend_friday.split("-");
    var y = parseInt(fri[0], 10);
    var m = parseInt(fri[1], 10) - 1;
    var d = parseInt(fri[2], 10);
    return Date.UTC(y, m, d) / 1000;
  }

  function satUnix(row) {
    return friUnix(row) + 86400;
  }

  function mondayUnix(row) {
    return friUnix(row) + 3 * 86400;
  }

  function reopenUnix(row) {
    return Math.floor(Date.parse(row.reopen_at_utc) / 1000);
  }

  function repayCloseTs(row) {
    var monday = mondayUnix(row);
    var closes = row.dex_closes || [];
    var lastOpen = null;
    for (var i = 0; i < closes.length; i++) {
      var open = closes[i][0];
      if (open < monday && (lastOpen === null || open > lastOpen)) lastOpen = open;
    }
    if (lastOpen === null) return null;
    return lastOpen + 3600;
  }

  function liquidationLabel(attempt) {
    if (attempt === "refused") return "Refused";
    if (attempt === "liquidated") return "Liquidated";
    return attempt.charAt(0).toUpperCase() + attempt.slice(1);
  }

  function fillEarned() {
    var e = data.earned;
    if (!e) return;
    function fillCol(prefix, r) {
      $(prefix + "-sales").textContent = String(r.sales);
      $(prefix + "-income").textContent = fmt2(r.income_raw / 1e6);
      $(prefix + "-repaid").textContent = fmt2(r.repaid_raw / 1e6);
      $(prefix + "-health").textContent = fmt4(r.hf_after_reopen);
      $(prefix + "-liquidation").textContent = liquidationLabel(r.liquidation_attempt);
      $(prefix + "-kept").textContent = fmt2(r.collateral_after_raw / 1e8);
    }
    fillCol("earned-funded", e.funded);
    fillCol("earned-none", e.no_income);
  }

  function fillReceipt() {
    var r = data.receipt;
    var g = r.agents.guarded;
    var c = r.agents.control;
    $("receipt-frozen").textContent = fmt2(r.frozen_price);
    $("receipt-reopen").textContent = fmt2(r.reopen_price);
    $("receipt-guarded-repay").textContent = fmt2(g.decision.repay_usd);
    $("receipt-guarded-hf").textContent = fmt4(g.hf_after_reopen);
    $("receipt-control-hf").textContent = fmt4(c.hf_after_reopen);
    $("receipt-guarded-kept").textContent = fmt4(g.collateral_after_raw / 1e8);
    $("receipt-control-kept").textContent = fmt4(c.collateral_after_raw / 1e8);
    $("receipt-guarded-result").textContent =
      g.liquidation_attempt.charAt(0).toUpperCase() + g.liquidation_attempt.slice(1);
    $("receipt-control-result").textContent =
      c.liquidation_attempt.charAt(0).toUpperCase() + c.liquidation_attempt.slice(1);
  }

  function fillWeekendSelect() {
    var sel = $("pick-weekend");
    sel.innerHTML = "";
    for (var i = 0; i < data.rows.length; i++) {
      var row = data.rows[i];
      var opt = document.createElement("option");
      opt.value = rowKey(row);
      opt.textContent = labelRow(row);
      sel.appendChild(opt);
    }
    sel.value = RECEIPT_KEY;
  }

  function parseHealthRaw(raw) {
    if (raw === null || raw === undefined) return null;
    var s = String(raw).trim();
    if (s === "") return null;
    var v = parseFloat(s);
    if (!isFinite(v)) return null;
    return v;
  }

  function clampHealth(v) {
    if (v < 1) return 1;
    if (v > 1.2) return 1.2;
    return v;
  }

  function currentHealth() {
    var parsed = parseHealthRaw($("pick-health").value);
    if (parsed === null) return data.start_hf_demo;
    return clampHealth(parsed);
  }

  function writeHealth(v) {
    $("pick-health").value = String(v);
  }

  function weekendWord(n) {
    return n === 1 ? "token-weekend" : "token-weekends";
  }

  function distinctCount(rows, key) {
    var seen = {};
    rows.forEach(function (row) {
      seen[row[key]] = true;
    });
    return Object.keys(seen).length;
  }

  function neededPhrase(n) {
    return n === 1 ? "was needed" : "were needed";
  }

  function alarmPhrase(n) {
    return n === 1 ? "1 was a false alarm" : n + " were false alarms";
  }

  function fillAcross(summary) {
    var el = document.getElementById("sim-across");
    el.innerHTML =
      "Across all " +
      summary.n +
      " token-weekends (" +
      distinctCount(data.rows, "symbol") +
      " tokens over " +
      distinctCount(data.rows, "weekend_friday") +
      " calendar weekends) at this health, the rule repaid on " +
      '<span class="num" data-testid="sim-repaid-count">' +
      summary.repaid_weekends +
      "</span> " +
      weekendWord(summary.repaid_weekends) +
      ". " +
      '<span class="num" data-testid="sim-needed-count">' +
      summary.saved +
      "</span> " +
      neededPhrase(summary.saved) +
      ". " +
      alarmPhrase(summary.unneeded_repays) +
      ".";
  }

  function updateSim() {
    var row = findRow($("pick-weekend").value);
    var h = currentHealth();
    var sim = Engine.simulate(row, h, data.band_pts, data.cf);
    var summary = Engine.summarize(data.rows, h, data.band_pts, data.cf);

    $("sim-action").textContent = sim.action;
    $("sim-repay").textContent = fmt2(sim.repay_usd);
    $("sim-guarded-hf").textContent = fmt4(sim.guarded_hf);
    $("sim-control-hf").textContent = fmt4(sim.control_hf);
    fillAcross(summary);

    var plain = document.getElementById("sim-plain");
    if (sim.action === "HOLD" && !sim.control_liquidated) {
      plain.textContent = "Nothing happens on this weekend at this health. No repay, no liquidation.";
    } else if (sim.action === "HOLD" && sim.control_liquidated) {
      plain.textContent = "The rule holds. Control is liquidated. Guarded is not saved.";
    } else if (sim.action === "REPAY" && sim.control_liquidated && sim.guarded_survives) {
      plain.textContent = "The rule repays. Control is liquidated. Guarded survives.";
    } else if (sim.action === "REPAY" && !sim.control_liquidated) {
      plain.textContent = "The rule repays, but control would have survived. A false alarm.";
    } else {
      plain.textContent = "The rule repays. Guarded health after reopen is " + fmt4(sim.guarded_hf) + ".";
    }

    var forkNote = document.getElementById("sim-fork-note");
    if (rowKey(row) === RECEIPT_KEY) {
      forkNote.textContent =
        "NVDAc 6 Nov is the weekend that was run on the fork. Other figures here are rule math.";
    } else {
      forkNote.textContent =
        "Only NVDAc 6 Nov was run on the fork. This row is rule math on recorded prices.";
    }

    drawChart(row, h, sim, false);
  }

  function el(name, attrs, kids) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", name);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, attrs[k]);
      });
    }
    if (kids) {
      kids.forEach(function (c) {
        if (typeof c === "string") node.appendChild(document.createTextNode(c));
        else if (c) node.appendChild(c);
      });
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function labelText(attrs, text) {
    var a = Object.assign(
      {
        fill: "#0a0a0a",
        "font-family": FONT,
        "font-size": "11",
      },
      attrs
    );
    return el("text", a, [text]);
  }

  function measureLabelWidth(host, text) {
    var node = labelText({ x: 0, y: 0, "font-size": "11", visibility: "hidden" }, text);
    host.appendChild(node);
    var w = 0;
    try {
      w = node.getComputedTextLength();
    } catch (err) {
      w = String(text).length * 6;
    }
    host.removeChild(node);
    return Math.ceil(w);
  }

  function stackLabelYs(preferred, yMin, yMax, step, avoidBands) {
    var items = preferred.map(function (y, i) {
      return { i: i, y: y };
    });
    items.sort(function (a, b) {
      return a.y - b.y || a.i - b.i;
    });
    var bands = (avoidBands || []).slice().sort(function (a, b) {
      return a - b;
    });
    function clearAvoid(y) {
      var out = y;
      for (var pass = 0; pass < bands.length + 2; pass++) {
        var moved = false;
        for (var b = 0; b < bands.length; b++) {
          if (Math.abs(out - bands[b]) < step) {
            out = out <= bands[b] ? bands[b] - step : bands[b] + step;
            moved = true;
          }
        }
        if (!moved) break;
      }
      return out;
    }
    for (var n = 0; n < items.length; n++) {
      var y = clearAvoid(items[n].y);
      if (n > 0 && y - items[n - 1].y < step) y = items[n - 1].y + step;
      items[n].y = y;
    }
    if (items.length && items[items.length - 1].y > yMax) {
      var shift = items[items.length - 1].y - yMax;
      for (var s = 0; s < items.length; s++) items[s].y -= shift;
    }
    if (items.length && items[0].y < yMin) {
      var shiftUp = yMin - items[0].y;
      for (var u = 0; u < items.length; u++) items[u].y += shiftUp;
    }
    for (var p = 0; p < items.length; p++) {
      var y3 = clearAvoid(items[p].y);
      if (p > 0 && y3 - items[p - 1].y < step) y3 = items[p - 1].y + step;
      items[p].y = Math.max(yMin, Math.min(yMax, y3));
    }
    for (var fix = 1; fix < items.length; fix++) {
      if (items[fix].y - items[fix - 1].y < step) {
        items[fix].y = Math.min(yMax, items[fix - 1].y + step);
      }
    }
    for (var back = items.length - 2; back >= 0; back--) {
      if (items[back + 1].y - items[back].y < step) {
        items[back].y = Math.max(yMin, items[back + 1].y - step);
      }
    }
    var out = new Array(preferred.length);
    for (var q = 0; q < items.length; q++) out[items[q].i] = items[q].y;
    return out;
  }

  function measureChart() {
    var wrap = document.getElementById("chart-wrap");
    var panel = document.getElementById("chart-panel");
    var w = Math.max(280, Math.floor(wrap.clientWidth || panel.clientWidth || 360));
    var phone = window.innerWidth < 900;
    var h;
    if (phone) {
      var cap = Math.floor(window.innerHeight * 0.4) - 8;
      h = Math.max(170, Math.min(cap, Math.floor(w * 0.72)));
    } else {
      var box = wrap.clientHeight;
      h = box > 120 ? box : Math.min(520, Math.max(320, Math.floor(w * 0.58)));
    }
    return { W: w, H: h, phone: phone };
  }

  function yScale(y0, y1, top, height) {
    return function (v) {
      var n = (v - y0) / (y1 - y0);
      return top + height - n * height;
    };
  }

  function polyline(points, attrs) {
    var d = points
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + p[0].toFixed(2) + " " + p[1].toFixed(2);
      })
      .join(" ");
    return el("path", Object.assign({ d: d, fill: "none" }, attrs));
  }

  function drawChart(row, h, sim, animating) {
    lastDraw = { row: row, h: h, sim: sim };
    var svg = document.getElementById("frozen-chart");
    var staticG = document.getElementById("chart-static");
    var revealG = document.getElementById("chart-reveal");
    var overlayG = document.getElementById("chart-overlay");
    clear(staticG);
    clear(revealG);
    clear(overlayG);

    var size = measureChart();
    var W = size.W;
    var H = size.H;
    var priceH = Math.floor(H * 0.52);
    var healthTop = PAD.t + priceH + PAD.mid;
    var healthH = H - healthTop - PAD.b;
    var loanLabel = "Loan price (frozen)";
    var dexLabelText = "DEX price";
    var receiptView = document.body.classList.contains("view-replay");
    var agents = data.receipt.agents;
    var guardedLabelText = "Guarded " + fmt4(receiptView ? agents.guarded.hf_after_reopen : sim.guarded_hf);
    var controlLabelText = "Control " + fmt4(receiptView ? agents.control.hf_after_reopen : sim.control_hf);
    var gutter = Math.max(
      measureLabelWidth(staticG, loanLabel),
      measureLabelWidth(staticG, dexLabelText),
      measureLabelWidth(staticG, guardedLabelText),
      measureLabelWidth(staticG, controlLabelText)
    ) + 10;
    var maxGutter = Math.max(72, Math.floor(W * 0.34));
    if (gutter > maxGutter) gutter = maxGutter;
    var afterStrip = Math.max(36, Math.floor((W - PAD.l - gutter) * 0.12));
    var xEnd = W - gutter;
    var plotRight = xEnd - afterStrip;
    var labelX = xEnd + 4;

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("width", String(W));
    svg.setAttribute("height", String(H));
    var clipRect = document.getElementById("reveal-rect");
    clipRect.setAttribute("width", String(W));
    clipRect.setAttribute("height", String(H));

    var t0 = satUnix(row);
    var t1 = reopenUnix(row);
    var closes = row.dex_closes || [];
    var repayTs = null;
    if (sim.action === "REPAY") {
      repayTs = repayCloseTs(row);
    }
    svg.setAttribute("data-repay-ts", repayTs === null ? "" : String(repayTs));

    function xs(t) {
      return PAD.l + ((t - t0) / (t1 - t0)) * (plotRight - PAD.l);
    }

    var prices = [row.frozen, row.reopen];
    for (var i = 0; i < closes.length; i++) prices.push(closes[i][1]);
    var pMin = Math.min.apply(null, prices);
    var pMax = Math.max.apply(null, prices);
    var pPad = (pMax - pMin) * 0.14 || 1;
    var yp = yScale(pMin - pPad, pMax + pPad, PAD.t, priceH);

    var repayNorm = 0;
    if (sim.action === "REPAY") {
      repayNorm = Engine.decide(h / data.cf, 1.0, data.cf, row.predicted_pct, data.band_pts).repay_usd;
    }
    var midGuarded = repayNorm > 0 ? h / (1 - repayNorm) : h;
    var healths = [h, 1.0, sim.control_hf, sim.guarded_hf, midGuarded];
    var hMin = Math.min.apply(null, healths.concat([0.92]));
    var hMax = Math.max.apply(null, healths.concat([1.12]));
    var hPad = (hMax - hMin) * 0.18 || 0.05;
    var yh = yScale(hMin - hPad, hMax + hPad, healthTop, healthH);

    chartGeom = { W: W, H: H, padL: PAD.l, padR: PAD.r };

    // Pane divider
    staticG.appendChild(
      el("line", {
        x1: PAD.l,
        x2: xEnd,
        y1: healthTop - PAD.mid / 2,
        y2: healthTop - PAD.mid / 2,
        stroke: "#0a0a0a",
        "stroke-width": "1",
        opacity: "0.25",
      })
    );

    staticG.appendChild(
      labelText(
        {
          x: PAD.l,
          y: healthTop + 2,
          "font-size": "11",
        },
        "Health"
      )
    );
    staticG.appendChild(labelText({ x: PAD.l, y: H - 8, "font-size": "11" }, "Sat"));
    staticG.appendChild(
      labelText(
        {
          x: plotRight,
          y: H - 8,
          "font-size": "11",
          "text-anchor": "middle",
        },
        "Reopen"
      )
    );

    // Price tick numbers
    var priceTickYs = stackLabelYs(
      [yp(row.frozen) + 4, yp(row.reopen) + 4],
      PAD.t + 10,
      PAD.t + priceH - 2,
      16
    );
    staticG.appendChild(
      labelText(
        {
          x: PAD.l - 6,
          y: priceTickYs[0],
          "font-family": MONO,
          "font-size": "11",
          "text-anchor": "end",
        },
        fmt2(row.frozen)
      )
    );
    staticG.appendChild(
      labelText(
        {
          x: PAD.l - 6,
          y: priceTickYs[1],
          "font-family": MONO,
          "font-size": "11",
          "text-anchor": "end",
        },
        fmt2(row.reopen)
      )
    );

    // Liquidation label (left of the line, not on it)
    var liqY = yh(1);
    var liqLabelY = liqY + 14;
    var healthTitleY = healthTop + 2;
    if (Math.abs(liqLabelY - healthTitleY) < LABEL_STEP) liqLabelY = healthTitleY + LABEL_STEP;
    staticG.appendChild(
      labelText(
        {
          x: PAD.l,
          y: liqLabelY,
          fill: "#c1121f",
          "font-size": "11",
        },
        "Liquidation"
      )
    );
    staticG.appendChild(
      labelText(
        {
          x: PAD.l - 6,
          y: liqY + 4,
          fill: "#c1121f",
          "font-family": MONO,
          "font-size": "11",
          "text-anchor": "end",
        },
        "1.00"
      )
    );

    // DEX closes
    var dexEndY = null;
    if (closes.length) {
      var dexPts = closes.map(function (c) {
        var t = Math.min(Math.max(c[0], t0), t1);
        return [xs(t), yp(c[1])];
      });
      revealG.appendChild(
        polyline(dexPts, {
          stroke: "#0a0a0a",
          "stroke-width": "1.25",
          opacity: "0.45",
        })
      );
      dexEndY = dexPts[dexPts.length - 1][1];
    }

    // Frozen loan price: straight then snap, then run after reopen
    var frozenPath = [
      [xs(t0), yp(row.frozen)],
      [xs(t1), yp(row.frozen)],
      [xs(t1), yp(row.reopen)],
      [xEnd, yp(row.reopen)],
    ];
    revealG.appendChild(
      polyline(frozenPath, {
        stroke: "#0a0a0a",
        "stroke-width": "2.75",
        "stroke-linejoin": "miter",
      })
    );

    // Price pane end labels in the right gutter
    var priceLabelYs = stackLabelYs(
      dexEndY === null ? [yp(row.reopen)] : [yp(row.reopen), dexEndY],
      PAD.t + 10,
      PAD.t + priceH - 2,
      LABEL_STEP,
      []
    );
    revealG.appendChild(
      labelText(
        {
          x: labelX,
          y: priceLabelYs[0],
          "font-size": "11",
        },
        loanLabel
      )
    );
    if (dexEndY !== null) {
      revealG.appendChild(
        labelText(
          {
            x: labelX,
            y: priceLabelYs[1],
            "font-size": "11",
          },
          dexLabelText
        )
      );
    }

    // Liquidation line
    revealG.appendChild(
      el("line", {
        x1: PAD.l,
        x2: xEnd,
        y1: yh(1),
        y2: yh(1),
        stroke: "#c1121f",
        "stroke-width": "1.5",
      })
    );

    var sameHealth = Math.abs(sim.guarded_hf - sim.control_hf) < 1e-9;
    var ctrlColor = sim.control_liquidated ? "#c1121f" : "#0a0a0a";
    var ctrlPts = [
      [xs(t0), yh(h)],
      [xs(t1), yh(h)],
      [xs(t1), yh(sim.control_hf)],
      [xEnd, yh(sim.control_hf)],
    ];
    var gPts;
    var repayX = repayTs !== null ? xs(Math.min(Math.max(repayTs, t0), t1)) : null;
    if (sim.action === "REPAY" && repayNorm > 0 && repayX !== null) {
      gPts = [
        [xs(t0), yh(h)],
        [repayX, yh(h)],
        [repayX, yh(midGuarded)],
        [xs(t1), yh(midGuarded)],
        [xs(t1), yh(sim.guarded_hf)],
        [xEnd, yh(sim.guarded_hf)],
      ];
    } else {
      gPts = [
        [xs(t0), yh(h)],
        [xs(t1), yh(h)],
        [xs(t1), yh(sim.guarded_hf)],
        [xEnd, yh(sim.guarded_hf)],
      ];
    }

    function drawControl() {
      revealG.appendChild(
        polyline(ctrlPts, {
          stroke: ctrlColor,
          "stroke-width": "2",
          "stroke-linejoin": "miter",
        })
      );
    }
    function drawGuarded() {
      revealG.appendChild(
        polyline(gPts, {
          stroke: "#0052FF",
          "stroke-width": "2.5",
          "stroke-linejoin": "miter",
        })
      );
    }
    // When paths coincide (HOLD), draw control last so it stays visible.
    if (sameHealth) {
      drawGuarded();
      drawControl();
    } else {
      drawControl();
      drawGuarded();
    }

    if (sim.action === "REPAY" && repayX !== null) {
      var repayLabelY = (yh(h) + yh(midGuarded)) / 2 + 4;
      if (Math.abs(repayLabelY - liqLabelY) < LABEL_STEP && Math.abs(repayX - PAD.l) < 80) {
        repayLabelY = liqLabelY + LABEL_STEP;
      }
      if (Math.abs(repayLabelY - healthTitleY) < LABEL_STEP && repayX < PAD.l + 90) {
        repayLabelY = healthTitleY + LABEL_STEP;
      }
      revealG.appendChild(
        labelText(
          {
            x: repayX - 6,
            y: repayLabelY,
            fill: "#0052FF",
            "font-size": "11",
            "text-anchor": "end",
          },
          "Repay"
        )
      );
    }

    // Health pane end labels in the right gutter, stepped clear of each other and liquidation.
    var healthLabelYs = stackLabelYs(
      [yh(sim.guarded_hf) + 4, yh(sim.control_hf) + 4],
      healthTop + 12,
      healthTop + healthH - 2,
      LABEL_STEP,
      [liqY + 4, liqLabelY]
    );
    revealG.appendChild(
      labelText(
        {
          x: labelX,
          y: healthLabelYs[0],
          fill: "#0052FF",
          "font-size": "11",
        },
        guardedLabelText
      )
    );
    revealG.appendChild(
      labelText(
        {
          x: labelX,
          y: healthLabelYs[1],
          fill: ctrlColor,
          "font-size": "11",
        },
        controlLabelText
      )
    );

    setReveal(animating ? 0 : 1);
  }

  function setReveal(p) {
    var rect = document.getElementById("reveal-rect");
    if (!chartGeom) return;
    var W = chartGeom.W;
    var padL = chartGeom.padL;
    var width;
    if (p <= 0) width = padL;
    else if (p >= 1) width = W;
    else width = padL + p * (W - padL);
    rect.setAttribute("width", String(width));
  }

  function playReveal() {
    if (animFrame) {
      cancelAnimationFrame(animFrame);
      animFrame = null;
    }
    if (reduced) {
      setReveal(1);
      return;
    }
    // Written exception to the 300ms product UI limit (DESIGN.md section 8): this is the replay of a
    // recorded weekend, a story animation the reader asks for with the Replay button. The sweep is the
    // content (Friday's frozen price against the hourly pool closes), so it runs at reading speed.
    // It never runs on load, it uses an ease-out curve, and prefers-reduced-motion skips it.
    var start = null;
    var duration = 2200;
    function tick(ts) {
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      var e = 1 - Math.pow(1 - p, 3);
      setReveal(e);
      if (p < 1) animFrame = requestAnimationFrame(tick);
      else animFrame = null;
    }
    setReveal(0);
    animFrame = requestAnimationFrame(tick);
  }

  function replay() {
    $("pick-weekend").value = RECEIPT_KEY;
    writeHealth(data.start_hf_demo);
    updateSim();
    var chart = document.getElementById("frozen-chart");
    if (chart && chart.scrollIntoView) {
      chart.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
    }
    playReveal();
  }

  function onHealthChange() {
    var parsed = parseHealthRaw($("pick-health").value);
    if (parsed === null) writeHealth(data.start_hf_demo);
    else writeHealth(clampHealth(parsed));
    updateSim();
  }

  function onResize() {
    if (!lastDraw) return;
    drawChart(lastDraw.row, lastDraw.h, lastDraw.sim, false);
  }

  function boot() {
    if (new URLSearchParams(window.location.search).get("view") === "replay") {
      document.body.classList.add("view-replay");
    }
    fillReceipt();
    fillEarned();
    fillWeekendSelect();
    var health = $("pick-health");
    writeHealth(data.start_hf_demo);
    $("pick-weekend").addEventListener("change", updateSim);
    health.addEventListener("input", updateSim);
    health.addEventListener("change", onHealthChange);
    document.getElementById("replay-btn").addEventListener("click", replay);
    window.addEventListener("resize", onResize);
    updateSim();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

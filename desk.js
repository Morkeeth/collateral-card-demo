(() => {
  const status = document.getElementById("desk-status");
  const result = document.getElementById("desk-result");
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const day = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", hourCycle: "h23", timeZone: "UTC",
  });
  const words = { ALLOW: "Allowed", REPAY_FIRST: "Repay first", REFUSE: "Refused" };

  function cell(row, text, cls) {
    const td = document.createElement("td");
    td.textContent = text;
    if (cls) td.className = cls;
    row.append(td);
  }

  function show(r) {
    const d = r.desk;
    document.getElementById("desk-observation").textContent =
      `${day.format(new Date(d.as_of_utc))} UTC · debt ${d.debt_usd} USDC · cash ${d.cash_usd} USDC`;
    const over = new Set(d.breaches.filter((b) => b.stock).map((b) => b.stock));
    const body = document.getElementById("desk-rows");
    for (const p of d.positions) {
      const tr = document.createElement("tr");
      cell(tr, p.stock);
      cell(tr, p.units);
      cell(tr, money.format(p.lending_value_usd));
      cell(tr, money.format(p.market_value_usd));
      cell(tr, `${p.gap_percent}%`);
      cell(tr, `${p.share_percent}%`, over.has(p.stock) ? "over" : "");
      body.append(tr);
    }
    document.getElementById("desk-hf-lender").textContent = d.health.lender_view;
    document.getElementById("desk-hf-weekend").textContent = d.health.weekend_view;
    document.getElementById("desk-floor").textContent = `Owner's floor ${d.health.floor}`;
    document.getElementById("desk-safe").textContent = money.format(d.spend.safe_now_usd);
    document.getElementById("desk-lender-safe").textContent =
      `Friday's price would allow ${money.format(d.spend.lender_would_allow_usd)}`;
    const breaches = document.getElementById("desk-breaches");
    for (const b of d.breaches) {
      const li = document.createElement("li");
      li.textContent = b.stock
        ? `${b.stock} is ${b.share_percent}% of the book, over the ${b.limit_percent}% limit. ${b.effect}`
        : `Weekend health ${b.health} is under the floor. ${b.effect}`;
      breaches.append(li);
    }
    const checks = document.getElementById("desk-checks");
    for (const c of r.checks) {
      const li = document.createElement("li");
      const verdict = document.createElement("b");
      verdict.textContent = words[c.action] || c.action;
      if (c.action === "REFUSE") verdict.className = "refuse";
      const repay = c.repay_usd ? ` Repay ${money.format(c.repay_usd)}.` : "";
      li.append(`Spend ${money.format(c.amount_usd)}: `, verdict, `. ${c.reason}${repay}`);
      checks.append(li);
    }
    const a = r.after_reopen;
    document.getElementById("desk-reopen").textContent =
      `When the lending price reopened, health was ${a.without_desk.health} without the repayment and ${a.with_desk.health} with it. ` +
      (a.floor_breached_without_desk ? "Without the desk the floor was broken." : "The floor held either way this weekend, so the repayment was caution, not a rescue.");
    result.hidden = false;
    status.hidden = true;
  }

  fetch("demo/desk.json")
    .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
    .then(show)
    .catch(() => { status.textContent = "The desk receipt could not load. Reload the page to retry."; });
})();

(() => {
  const status = document.getElementById("desk-status");
  const result = document.getElementById("desk-result");
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const day = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", hourCycle: "h23", timeZone: "UTC",
  });
  const words = { ALLOW: "Allowed", CUT: "Cut", REFUSE: "Refused" };

  function cell(row, text, cls) {
    const td = document.createElement("td");
    td.textContent = text;
    if (cls) td.className = cls;
    row.append(td);
  }

  const weekday = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" });
  const set = (id, text) => { document.getElementById(id).textContent = text; };

  // The first screen: one spend request and the two answers to it, all read from the receipt.
  function ask(r) {
    const c = r.checks.find((x) => x.action === "CUT") || r.checks[0];
    const when = new Date(c.as_of_utc || r.desk.as_of_utc);
    set("ask-when", `On ${weekday.format(when)} ${day.format(when)} UTC, before the lending price reopens`);
    set("ask-amount", money.format(c.amount_usd));
    set("ask-split", Number(c.borrow_usd) > 0
      ? `, ${money.format(c.from_cash_usd)} from cash and ${money.format(c.borrow_usd)} borrowed` : " from cash");
    set("ask-lender-word", c.lender_would_allow ? "Yes, up to" : "No, at most");
    set("ask-lender", money.format(r.desk.spend.lender_would_allow_usd));
    const verbs = { ALLOW: "Allowed", CUT: "Cut to", REFUSE: "Refused" };
    set("ask-action", verbs[c.action] || c.action);
    set("ask-allowed", c.action === "REFUSE" ? "" : money.format(c.allowed_usd));
    const a = r.after_reopen;
    set("ask-why", a && a.floor_breached_without_desk
      ? `When the price reopened, the full ${money.format(a.requested_usd)} would have put the loan under the owner's safety floor. The cut amount kept it above.`
      : c.reason);
  }

  function show(r) {
    ask(r);
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
      const split = Number(c.borrow_usd) > 0 ? ` (${c.from_cash_usd} cash, ${c.borrow_usd} borrowed)` : " (cash)";
      li.append(`Spend ${money.format(c.amount_usd)}${split}: `, verdict, `. ${c.reason}`);
      checks.append(li);
    }
    const a = r.after_reopen;
    document.getElementById("desk-reopen").textContent =
      `When the lending price reopened, the full ${a.requested_usd} USDC spend left health at ${a.without_desk.health}` +
      (a.floor_breached_without_desk ? `, under the owner's ${a.floor} floor. ` : `, above the owner's ${a.floor} floor. `) +
      `The desk's ${a.with_desk.spent_usd} USDC left it at ${a.with_desk.health}. Liquidation starts at 1.0, so neither path was liquidated.`;
    result.hidden = false;
    status.hidden = true;
  }

  fetch("demo/desk.json")
    .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
    .then(show)
    .catch(() => {
      const msg = "The desk receipt could not load. Reload the page to retry.";
      status.textContent = msg;
      document.querySelector(".ask").classList.add("ask-failed");
      set("ask-why", msg);
    });
})();

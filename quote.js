(() => {
  const demo = document.getElementById("quote-demo");
  const result = document.getElementById("quote-result");
  const status = document.getElementById("quote-status");
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const utc = new Intl.DateTimeFormat("en-GB", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23", timeZone: "UTC",
  });

  const day = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", hourCycle: "h23", timeZone: "UTC",
  });

  function showReceipt(receipt) {
    const quote = receipt.quote;
    const gap = Number(quote.pool_minus_lending_percent);
    const gapLabel = gap < 0 ? "Below lending price" : gap > 0 ? "Above lending price" : "Gap from lending price";
    const fields = {
      "quote-observation": `${quote.stock} · ${day.format(new Date(quote.as_of_utc))} UTC`,
      "quote-lender": money.format(quote.lending_price_usd),
      "quote-lender-time": `${utc.format(new Date(quote.lending_price_at_utc))} UTC`,
      "quote-market": money.format(quote.pool_close_usd),
      "quote-market-time": `${utc.format(new Date(quote.pool_close_at_utc))} UTC`,
      "quote-gap-label": gapLabel,
      "quote-gap": `${Math.abs(gap).toFixed(2)}%`,
    };
    for (const [id, value] of Object.entries(fields)) {
      document.getElementById(id).textContent = value;
    }
    result.hidden = false;
    status.hidden = true;
  }

  let loading = false;
  demo.addEventListener("toggle", async () => {
    if (!demo.open || !result.hidden || loading) return;
    loading = true;
    status.textContent = "Loading checkout receipt…";
    try {
      const response = await fetch("demo/paid-quote.json");
      if (!response.ok) throw new Error("Receipt unavailable");
      showReceipt(await response.json());
    } catch {
      status.textContent = "The receipt could not load. Close and reopen the paid response to retry.";
    } finally {
      loading = false;
    }
  });

  function openDirectQuote() {
    if (window.location.hash === "#paid-quote-heading") demo.open = true;
  }
  window.addEventListener("hashchange", openDirectQuote);
  openDirectQuote();
})();

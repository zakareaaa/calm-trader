"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  let S = null;              // last /api/state
  let chartData = null;
  let range = "1D";
  let side = "buy";
  let kind = "buy_market";
  let lastPrice = 0;
  let pendingIdea = null;

  // ---------- helpers ----------
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { "X-Calm-Trader": "1", ...(opts.body ? { "Content-Type": "application/json" } : {}) },
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      const err = new Error((data && data.detail && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || res.statusText);
      err.data = data;
      throw err;
    }
    return data;
  }
  const n = (v) => { const x = parseFloat(String(v ?? "").replace(/,/g, "")); return isFinite(x) ? x : 0; };
  const fmt = (v, d = 2) => (isFinite(v) ? Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—");
  const signed = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), d);
  const cls = (v) => (v > 0 ? "gain" : v < 0 ? "loss" : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const when = (ms) => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  function banner(msg) {
    const b = $("banner");
    if (!msg) { b.hidden = true; return; }
    b.hidden = false;
    b.innerHTML = msg;
  }

  // ---------- data loading ----------
  async function loadState() {
    try {
      S = await api("/api/state");
      banner(null);
      lastPrice = S.price;
      renderAll();
    } catch (e) {
      banner(`<b>Couldn't load your account.</b> ${esc(e.message)}<br><span class="muted">Check that your demo API key and secret are in the <code>.env</code> file and that the server terminal shows no errors.</span>`);
    }
  }
  async function loadChart() {
    try {
      chartData = await api("/api/chart?range=" + range);
      const st = $("structure");
      st.textContent = chartData.structure.text;
      st.className = "structure " + chartData.structure.trend;
      $("maHint").textContent = chartData.ma25 ? ""
        : "On this view the 25-day and 99-day averages are shown as today's level (dashed lines). An arrow means the level is off the chart. Switch to 3M or 1Y to see them move.";
      drawChart();
    } catch (e) { /* banner already covers it */ }
  }
  async function loadPrice() {
    try {
      const q = await api("/api/price");
      const price = q.price;
      $("bid").textContent = fmt(q.bid);
      $("ask").textContent = fmt(q.ask);
      $("spread").textContent = `${fmt(q.spread)} (${q.spread_pct < 0.01 ? "<0.01" : fmt(q.spread_pct)}%)`;
      const el = $("price");
      el.classList.remove("up", "down");
      if (lastPrice) el.classList.add(price >= lastPrice ? "up" : "down");
      lastPrice = price;
      el.textContent = fmt(price);
      if (S) { S.price = price; renderPosition(); updateHint(); }
      if (chartData && chartData.points.length) { chartData.points[chartData.points.length - 1].c = price; drawChart(); }
    } catch (e) { /* keep last price */ }
  }
  async function loadJournal() {
    try { renderJournal(await api("/api/journal")); } catch (e) { /* ignore */ }
  }

  // ---------- rendering ----------
  function renderAll() {
    $("pair").textContent = `${S.base}/${S.quote}`;
    $("price").textContent = fmt(S.price);
    const chg = $("chg");
    chg.textContent = `${signed(S.change24)}% 24h`;
    chg.className = "chip num " + cls(S.change24);
    $("acctValue").textContent = fmt(S.account_value) + " " + S.quote;
    renderPosition();
    renderOrders();
    renderNotes("highlights", S.highlights);
    renderNotes("mentor", S.mentor);
    $("checklist").innerHTML = S.checklist.map((c) => `<li><b>${esc(c.title)}:</b> ${esc(c.detail)}</li>`).join("");
    const st = S.stats;
    $("jstats").innerHTML = `Realized P&amp;L <span class="num ${cls(S.realized)}">${signed(S.realized)}</span> · `
      + `Winning sells ${st.wins}/${st.sells} · Fees paid <span class="num">${fmt(st.fees_paid)}</span> · Trades today ${st.trades_today}`;
    updateHint();
    drawChart();
  }

  function stat(k, v, s, c = "") {
    return `<div class="stat"><span class="k">${k}</span><span class="v ${c}">${v}</span>${s ? `<span class="s">${s}</span>` : ""}</div>`;
  }

  function renderPosition() {
    if (!S) return;
    const p = S.position, b = S.balances, price = S.price;
    const el = $("position");
    const usdt = stat("USDT available", fmt(b.usdt_free), b.usdt_locked ? `${fmt(b.usdt_locked)} locked in orders` : "");
    if (!p) {
      el.innerHTML = stat(`${S.base} held`, fmt(b.base_free + b.base_locked, 8), "No position from your trade history") + usdt;
      $("targetPrice").textContent = "—";
      return;
    }
    const valueNow = p.qty * price * (1 - S.fee);
    const pnl = valueNow - p.cost;
    const pct = p.cost ? (valueNow / p.cost - 1) * 100 : 0;
    const toBe = p.break_even - price;
    el.innerHTML =
      stat(`${S.base} held`, fmt(p.qty, 8), `worth ${fmt(p.qty * price)} ${S.quote}`) +
      stat("Average buy price", fmt(p.avg_price), `you paid ${fmt(p.cost)} incl. fees`) +
      stat("Break-even (sell all)", fmt(p.break_even), toBe > 0 ? `${fmt(toBe)} above the price now` : "price is above it", "") +
      stat("If you sold now", signed(pnl), `${signed(pct)}% after fees`, cls(pnl)) +
      usdt;
    const want = n($("wantProfit").value);
    const tp = want > 0 ? (p.cost + want) / (p.qty * (1 - S.fee)) : 0;
    $("targetPrice").textContent = tp ? fmt(tp) : "—";
  }

  function renderOrders() {
    const el = $("orders");
    if (!S.open_orders.length) {
      el.innerHTML = `<p class="empty">No open orders.${S.position ? " Your BTC has no automatic exit right now." : ""}</p>`;
      return;
    }
    el.innerHTML = S.open_orders.map((o) => {
      const tone = o.type === "LIMIT_MAKER" || o.type.startsWith("TAKE_PROFIT") || (o.side === "SELL" && o.type === "LIMIT") ? "tp"
        : o.type.startsWith("STOP_LOSS") ? "sl" : "";
      const trigger = o.stopPrice ? `triggers at ${fmt(o.stopPrice)}, then sells at ${fmt(o.price)} or better` : `at ${fmt(o.price)}`;
      const dist = ((o.stopPrice || o.price) / S.price - 1) * 100;
      return `<div class="order">
        <span class="what ${tone}">${esc(o.label)}</span>
        <span class="detail">${o.side === "BUY" ? "Buy" : "Sell"} <span class="num">${fmt(o.qty, 5)}</span> ${S.base} ${trigger} · <span class="num">${signed(dist)}%</span> from now${o.inPlan ? " · cancelling one cancels both" : ""}</span>
        <button type="button" class="small" data-cancel="${o.orderId}">Cancel</button>
      </div>`;
    }).join("");
  }

  function renderNotes(id, items) {
    $(id).innerHTML = items.map((h) => `<li class="${h.level}"><div class="t">${esc(h.title)}</div><div class="d">${esc(h.detail)}</div></li>`).join("")
      || `<li class="info"><div class="d">Nothing notable right now.</div></li>`;
  }

  const KIND_TEXT = { buy_market: "Buy now", buy_limit: "Buy at a price", sell_market: "Sell now", sell_limit: "Sell at a price", exit_plan: "Exit plan" };
  const FEEL_TEXT = { calm: "Calm", excited: "Excited", fomo: "FOMO", fearful: "Fearful", revenge: "Revenge", bored: "Bored" };

  function renderJournal(rows) {
    const tb = $("journal").querySelector("tbody");
    if (!rows.length) { tb.innerHTML = `<tr><td colspan="6" class="empty">Your trades and the reasons behind them will appear here.</td></tr>`; return; }
    tb.innerHTML = rows.map((r) => {
      const warns = JSON.parse(r.warnings || "[]");
      const action = r.kind.startsWith("buy") ? `${KIND_TEXT[r.kind]} · ${fmt(r.amount_usdt)} USDT` : `${KIND_TEXT[r.kind]} · ${fmt(r.sell_pct, 0)}%`;
      const plan = [r.take_profit ? `TP ${fmt(r.take_profit)}` : "", r.stop_loss ? `SL ${fmt(r.stop_loss)}` : ""].filter(Boolean).join(" · ");
      return `<tr>
        <td class="num">${when(r.created_ms)}</td>
        <td>${esc(action)}${plan ? `<div class="muted num">${plan}</div>` : ""}</td>
        <td>${esc(r.reason)}</td>
        <td>${esc(FEEL_TEXT[r.feeling] || r.feeling || "")}${r.confidence ? `<div class="muted">confidence ${r.confidence}/5</div>` : ""}</td>
        <td class="muted">${warns.length ? warns.map(esc).join("<br>") : "None"}</td>
        <td><textarea rows="2" id="rv-${r.id}" aria-label="Review for trade ${r.id}" placeholder="What happened? What would you do differently?">${esc(r.review || "")}</textarea>
          <button type="button" class="small save" data-review="${r.id}">Save</button></td>
      </tr>`;
    }).join("");
  }

  // ---------- chart ----------
  const canvas = $("chart"), tip = $("tip");
  let geo = null;

  function drawChart() {
    if (!chartData || !chartData.points.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const css = getComputedStyle(document.documentElement);
    const C = (v) => css.getPropertyValue(v).trim();
    const pts = chartData.points;
    const pad = { l: 8, r: 78, t: 12, b: 24 };

    let lo = Math.min(...pts.map((p) => p.c)), hi = Math.max(...pts.map((p) => p.c));
    const lines = [];
    if (S && S.position) lines.push({ y: S.position.break_even, color: C("--accent"), label: "Break-even" });
    if (S) S.open_orders.forEach((o) => {
      const y = o.stopPrice || o.price;
      const isStop = o.type.startsWith("STOP_LOSS");
      lines.push({ y, color: isStop ? C("--loss") : (o.side === "SELL" ? C("--gain") : "#9fb4cc"), label: isStop ? "Stop" : (o.side === "SELL" ? "Take-profit" : "Buy order") });
    });
    // on intraday views the daily averages are flat levels, so draw them as labelled reference lines
    if (!chartData.ma25 && chartData.ma_now) {
      if (chartData.ma_now.ma25) lines.push({ y: chartData.ma_now.ma25, color: "#6fa8ff", label: "25-day avg" });
      if (chartData.ma_now.ma99) lines.push({ y: chartData.ma_now.ma99, color: "#b48ee0", label: "99-day avg" });
    }
    const span = hi - lo || hi * 0.01;
    lines.forEach((l) => { if (l.y > lo - span * 0.6 && l.y < hi + span * 0.6) { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); } });
    [chartData.ma25, chartData.ma99].forEach((arr) => (arr || []).forEach((v) => {
      if (v != null && v > lo - span * 0.6 && v < hi + span * 0.6) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }));
    (chartData.swings || []).forEach((s) => { lo = Math.min(lo, s.price); hi = Math.max(hi, s.price); });
    const m = (hi - lo) * 0.08; lo -= m; hi += m;

    const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    const X = (t) => pad.l + (t - t0) / (t1 - t0 || 1) * (W - pad.l - pad.r);
    const Y = (v) => pad.t + (hi - v) / (hi - lo) * (H - pad.t - pad.b);
    geo = { X, Y, pts, pad, W, H };

    // grid + axis labels
    ctx.font = "11px " + C("--font-num");
    ctx.fillStyle = C("--muted");
    ctx.strokeStyle = C("--line");
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const v = lo + (hi - lo) * i / 4, y = Y(v);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.fillText(fmt(v, 0), W - pad.r + 6, y + 4);
    }
    const labelsAt = [0, Math.floor(pts.length / 2), pts.length - 1];
    labelsAt.forEach((i, j) => {
      const d = new Date(pts[i].t);
      const txt = chartData.interval === "1d" ? d.toLocaleDateString([], { month: "short", day: "numeric" }) : d.toLocaleString([], { weekday: range === "1W" ? "short" : undefined, hour: "2-digit", minute: "2-digit" });
      const w = ctx.measureText(txt).width;
      const x = Math.min(Math.max(X(pts[i].t) - (j === 2 ? w : j === 1 ? w / 2 : 0), pad.l), W - pad.r - w);
      ctx.fillText(txt, x, H - 6);
    });

    // area + line
    const first = pts[0].c, last = pts[pts.length - 1].c;
    const lineColor = last >= first ? C("--gain") : C("--loss");
    const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
    grad.addColorStop(0, lineColor + "33"); grad.addColorStop(1, lineColor + "00");
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(p.t), Y(p.c)) : ctx.moveTo(X(p.t), Y(p.c))));
    ctx.lineTo(X(t1), H - pad.b); ctx.lineTo(X(t0), H - pad.b); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(p.t), Y(p.c)) : ctx.moveTo(X(p.t), Y(p.c))));
    ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke();

    // moving averages
    [[chartData.ma25, "#6fa8ff"], [chartData.ma99, "#b48ee0"]].forEach(([arr, color]) => {
      if (!arr) return;
      ctx.beginPath();
      let started = false;
      arr.forEach((v, i) => {
        if (v == null) return;
        const x = X(pts[i].t), y = Y(v);
        if (y < pad.t || y > H - pad.b) { started = false; return; }
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
    });

    // swing highs and lows
    ctx.font = "600 11px " + C("--font-num");
    (chartData.swings || []).forEach((s) => {
      const x = X(s.t), y = Y(s.price);
      ctx.fillStyle = C("--ink");
      ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
      const label = s.kind;
      const w = ctx.measureText(label).width;
      ctx.fillText(label, x - w / 2, s.kind === "H" ? y - 7 : y + 15);
    });

    // reference lines
    ctx.font = "11px " + C("--font-num");
    ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
    let xTop = pad.l + 4, xBot = pad.l + 4;   // labels of lines pinned to an edge sit side by side, not on top of each other
    lines.forEach((l) => {
      let y = Y(l.y), off = "", x = pad.l + 4;
      const txt = () => `${l.label} ${fmt(l.y, 0)}${off}`;
      if (y < pad.t) { y = pad.t; off = " ↑"; x = xTop; xTop += ctx.measureText(txt()).width + 14; }
      else if (y > H - pad.b) { y = H - pad.b; off = " ↓"; x = xBot; xBot += ctx.measureText(txt()).width + 14; }
      ctx.strokeStyle = l.color;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.fillStyle = l.color;
      ctx.fillText(txt(), x, y - 4);
    });
    ctx.setLineDash([]);

    // my trades
    chartData.markers.forEach((mk) => {
      const x = X(mk.t), y = Y(mk.price);
      if (x < pad.l || x > W - pad.r) return;
      ctx.fillStyle = mk.side === "buy" ? C("--gain") : C("--loss");
      ctx.beginPath();
      if (mk.side === "buy") { ctx.moveTo(x, y + 4); ctx.lineTo(x - 6, y + 14); ctx.lineTo(x + 6, y + 14); }
      else { ctx.moveTo(x, y - 4); ctx.lineTo(x - 6, y - 14); ctx.lineTo(x + 6, y - 14); }
      ctx.closePath(); ctx.fill();
    });

    // current price tag
    const yNow = Y(last);
    ctx.fillStyle = lineColor;
    ctx.fillRect(W - pad.r + 2, yNow - 9, pad.r - 4, 18);
    ctx.fillStyle = "#0d1117";
    ctx.font = "600 11px " + C("--font-num");
    ctx.fillText(fmt(last, 0), W - pad.r + 6, yNow + 4);
  }

  canvas.addEventListener("mousemove", (e) => {
    if (!geo) return;
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    let best = geo.pts[0], bd = Infinity;
    geo.pts.forEach((p) => { const d = Math.abs(geo.X(p.t) - x); if (d < bd) { bd = d; best = p; } });
    tip.hidden = false;
    tip.textContent = `${new Date(best.t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}  ${fmt(best.c)}`;
    tip.style.left = Math.min(geo.X(best.t) + 10, r.width - 170) + "px";
    tip.style.top = Math.max(geo.Y(best.c) - 30, 0) + "px";
  });
  canvas.addEventListener("mouseleave", () => { tip.hidden = true; });
  window.addEventListener("resize", drawChart);

  document.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", () => {
    range = b.dataset.range;
    document.querySelectorAll("[data-range]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    loadChart();
  }));

  // ---------- ticket ----------
  const HINTS = {
    buy_market: "Buys immediately at the best sellers' price. You can attach an exit plan that's placed as soon as it fills.",
    buy_limit: "Waits in the order book until the price comes down to yours. Set the exit plan after it fills.",
    exit_plan: "Sells automatically at your take-profit OR your stop-loss, whichever comes first. Works while you sleep.",
    sell_limit: "Waits until the price rises to yours, then sells.",
    sell_market: "Sells immediately at the best buyers' price.",
  };

  function setSide(s) {
    side = s;
    $("tabBuy").setAttribute("aria-selected", String(s === "buy"));
    $("tabSell").setAttribute("aria-selected", String(s === "sell"));
    $("modeBuy").hidden = s !== "buy";
    $("modeSell").hidden = s !== "sell";
    const group = s === "buy" ? $("modeBuy") : $("modeSell");
    const pressed = group.querySelector('[aria-pressed="true"]');
    setKind(pressed.dataset.kind);
  }

  function setKind(k) {
    kind = k;
    const group = k.startsWith("buy") ? $("modeBuy") : $("modeSell");
    group.querySelectorAll("[data-kind]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === k)));
    const isBuy = k.startsWith("buy");
    $("fAmount").hidden = !isBuy;
    $("fPct").hidden = isBuy;
    $("fPrice").hidden = !(k === "buy_limit" || k === "sell_limit");
    $("fExit").hidden = !(k === "buy_market" || k === "buy_limit" || k === "exit_plan");
    $("exitLegend").textContent = k === "exit_plan" ? "Your exit prices" : "Exit plan (optional, recommended)";
    const btn = $("reviewBtn");
    btn.textContent = "Review " + (isBuy ? "buy" : "sell");
    if ((k === "buy_limit" || k === "sell_limit") && !n($("limitPrice").value) && S) $("limitPrice").value = Math.round(S.price);
    updateHint();
  }

  function updateHint() {
    let h = HINTS[kind] || "";
    if (S && !kind.startsWith("buy")) {
      const free = S.balances.base_free;
      h += ` You have ${fmt(free, 8)} ${S.base} free to sell` + (S.balances.base_locked ? ` (${fmt(S.balances.base_locked, 8)} locked in orders).` : ".");
    }
    $("modeHint").textContent = h;
  }

  // profit/loss amount -> price
  function basis() {
    if (!S) return null;
    const fee = S.fee;
    if (kind.startsWith("buy")) {
      const entry = kind === "buy_limit" ? n($("limitPrice").value) : S.price;
      const amt = n($("amount").value);
      if (!(entry > 0 && amt > 0)) return null;
      const qty = amt / entry * (1 - fee);
      return { cost: amt, qty, fee };
    }
    const qty = S.balances.base_free * n($("pct").value) / 100;
    const avg = S.position ? S.position.avg_price : S.price;
    if (!(qty > 0)) return null;
    return { cost: avg * qty, qty, fee };
  }
  function fromAmounts(which) {
    const b = basis(); if (!b) return;
    if (which === "tp") {
      const v = n($("tpAmt").value);
      if (v > 0) $("tp").value = ((b.cost + v) / (b.qty * (1 - b.fee))).toFixed(2);
    } else {
      const v = n($("slAmt").value);
      if (v > 0 && v < b.cost) $("sl").value = ((b.cost - v) / (b.qty * (1 - b.fee))).toFixed(2);
    }
  }
  $("tpAmt").addEventListener("input", () => fromAmounts("tp"));
  $("slAmt").addEventListener("input", () => fromAmounts("sl"));
  ["amount", "limitPrice", "pct"].forEach((id) => $(id).addEventListener("input", () => { fromAmounts("tp"); fromAmounts("sl"); }));
  $("tp").addEventListener("input", () => { $("tpAmt").value = ""; });
  $("sl").addEventListener("input", () => { $("slAmt").value = ""; });

  $("tabBuy").addEventListener("click", () => setSide("buy"));
  $("tabSell").addEventListener("click", () => setSide("sell"));
  document.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => setKind(b.dataset.kind)));
  document.querySelectorAll("[data-amt]").forEach((b) => b.addEventListener("click", () => { $("amount").value = b.dataset.amt; fromAmounts("tp"); fromAmounts("sl"); }));
  document.querySelectorAll("[data-pct]").forEach((b) => b.addEventListener("click", () => { $("pct").value = b.dataset.pct; fromAmounts("tp"); fromAmounts("sl"); }));
  $("wantProfit").addEventListener("input", renderPosition);
  $("useTarget").addEventListener("click", () => {
    const t = n($("targetPrice").textContent);
    if (!t) return;
    setSide("sell"); setKind("exit_plan");
    $("pct").value = 100; $("tp").value = t.toFixed(2); $("tpAmt").value = "";
    $("tp").focus();
  });

  function idea() {
    return {
      kind,
      amount_usdt: n($("amount").value),
      sell_pct: n($("pct").value),
      price: n($("limitPrice").value),
      take_profit: $("fExit").hidden ? 0 : n($("tp").value),
      stop_loss: $("fExit").hidden ? 0 : n($("sl").value),
      reason: $("reason").value,
    };
  }

  function summary(o, nums) {
    const b = S.base;
    switch (o.kind) {
      case "buy_market": return `Buy ${fmt(o.amount_usdt)} USDT of ${b} now, at about ${fmt(S.price)}.`;
      case "buy_limit": return `Buy ${fmt(o.amount_usdt)} USDT of ${b} if the price reaches ${fmt(o.price)}.`;
      case "sell_market": return `Sell ${fmt(o.sell_pct, 0)}% of your ${b} (${fmt(nums.qty, 8)}) now, at about ${fmt(S.price)}.`;
      case "sell_limit": return `Sell ${fmt(o.sell_pct, 0)}% of your ${b} (${fmt(nums.qty, 8)}) when the price reaches ${fmt(o.price)}.`;
      case "exit_plan": return `Sell ${fmt(o.sell_pct, 0)}% of your ${b} automatically: at ${fmt(o.take_profit)} if it rises, or at ${fmt(o.stop_loss)} if it falls.`;
    }
    return "";
  }

  function openModal(o, rv) {
    pendingIdea = o;
    const nums = rv.numbers || {};
    $("mSummary").textContent = summary(o, nums);
    const parts = [];
    if (nums.qty != null) parts.push(stat(o.kind.startsWith("buy") ? `${S.base} you'll get` : `${S.base} to sell`, fmt(nums.qty, 8)));
    if (nums.trade_break_even) parts.push(stat("This trade's break-even", fmt(nums.trade_break_even)));
    if (nums.break_even_after) parts.push(stat("Break-even of all your BTC after", fmt(nums.break_even_after)));
    if (nums.break_even) parts.push(stat("Your break-even", fmt(nums.break_even)));
    if (nums.gain_at_target != null) parts.push(stat("If take-profit hits", signed(nums.gain_at_target), "after fees", cls(nums.gain_at_target)));
    if (nums.loss_at_stop != null) parts.push(stat("If stop-loss hits", signed(-nums.loss_at_stop), nums.risk_pct != null ? `${fmt(nums.risk_pct)}% of your account` : "after fees", "loss"));
    if (nums.reward_risk) parts.push(stat("Reward : risk", `1 : ${fmt(nums.reward_risk)}`));
    $("mNumbers").innerHTML = parts.join("");
    const LBL = { block: "Fix first:", warn: "Warning:", info: "Note:" };
    $("mChecks").innerHTML = rv.checks.map((c) => `<li class="${c.level}"><span class="lvl">${LBL[c.level]}</span>${esc(c.msg)}</li>`).join("");
    $("mAckWrap").hidden = !rv.needs_ack;
    $("mAck").checked = false;
    $("mError").textContent = "";
    const confirm = $("mConfirm");
    confirm.disabled = rv.blocked || rv.needs_ack;
    confirm.textContent = rv.blocked ? "Fix the issues above first" : "Place order";
    $("modal").hidden = false;
    (rv.blocked ? $("mCancel") : confirm).focus();
  }
  function closeModal() { $("modal").hidden = true; pendingIdea = null; $("reviewBtn").focus(); }
  $("mAck").addEventListener("change", (e) => { $("mConfirm").disabled = !e.target.checked; });
  $("mCancel").addEventListener("click", closeModal);
  $("modal").addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  $("ticket").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!S) return;
    const o = idea();
    try {
      const rv = await api("/api/review", { method: "POST", body: JSON.stringify(o) });
      openModal(o, rv);
    } catch (err) {
      banner(`<b>Couldn't review the order.</b> ${esc(err.message)}`);
    }
  });

  $("mConfirm").addEventListener("click", async () => {
    if (!pendingIdea) return;
    const btn = $("mConfirm");
    btn.disabled = true; btn.textContent = "Sending…";
    try {
      const out = await api("/api/orders", { method: "POST", body: JSON.stringify({
        idea: pendingIdea, acknowledged: $("mAck").checked,
        confidence: Number($("confidence").value), feeling: $("feeling").value,
      }) });
      closeModal();
      $("reason").value = ""; $("tpAmt").value = ""; $("slAmt").value = "";
      if (out.notes && out.notes.length) banner(esc(out.notes.join(" ")));
      await Promise.all([loadState(), loadChart(), loadJournal()]);
    } catch (err) {
      $("mError").textContent = err.message;
      btn.disabled = false; btn.textContent = "Place order";
    }
  });

  // cancel + journal review (delegated)
  document.addEventListener("click", async (e) => {
    const c = e.target.closest("[data-cancel]");
    if (c) {
      c.disabled = true; c.textContent = "Cancelling…";
      try { await api("/api/orders/" + c.dataset.cancel, { method: "DELETE" }); await Promise.all([loadState(), loadChart()]); }
      catch (err) { banner(`<b>Couldn't cancel.</b> ${esc(err.message)}`); c.disabled = false; c.textContent = "Cancel"; }
      return;
    }
    const r = e.target.closest("[data-review]");
    if (r) {
      const id = r.dataset.review;
      try { await api(`/api/journal/${id}/review`, { method: "POST", body: JSON.stringify({ text: $("rv-" + id).value }) }); r.textContent = "Saved"; setTimeout(() => (r.textContent = "Save"), 1500); }
      catch (err) { r.textContent = "Failed"; }
    }
  });

  // ---------- start ----------
  setSide("buy");
  loadState().then(loadChart);
  loadPrice();
  loadJournal();
  setInterval(loadPrice, 3000);
  setInterval(loadState, 20000);
  setInterval(loadChart, 60000);
})();

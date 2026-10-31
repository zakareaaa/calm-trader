"""Plain-language market highlights.

These describe what the price HAS done, so you can see the situation at a
glance. None of them predicts what it WILL do.
"""
from __future__ import annotations


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def moving_average(values: list[float], n: int) -> list[float | None]:
    """Simple moving average for every point (None until there's enough history)."""
    out: list[float | None] = []
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def find_swings(points: list[dict], k: int) -> list[dict]:
    """Swing highs/lows: a candle whose high (low) is the highest (lowest) of the
    k candles on each side. Consecutive same-type swings keep only the extreme one,
    so the result alternates H, L, H, L like the zigzag a trader would draw."""
    raw = []
    for i in range(k, len(points) - k):
        window = points[i - k:i + k + 1]
        if points[i]["h"] == max(p["h"] for p in window):
            raw.append({"i": i, "t": points[i]["t"], "price": points[i]["h"], "kind": "H"})
        elif points[i]["l"] == min(p["l"] for p in window):
            raw.append({"i": i, "t": points[i]["t"], "price": points[i]["l"], "kind": "L"})
    swings: list[dict] = []
    for s in raw:
        if swings and swings[-1]["kind"] == s["kind"]:
            prev = swings[-1]
            better = s["price"] > prev["price"] if s["kind"] == "H" else s["price"] < prev["price"]
            if better:
                swings[-1] = s
        else:
            swings.append(s)
    return swings


def describe_structure(swings: list[dict]) -> dict:
    highs = [s["price"] for s in swings if s["kind"] == "H"][-2:]
    lows = [s["price"] for s in swings if s["kind"] == "L"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return {"trend": "unclear", "text": "Not enough clear highs and lows in this range to read a trend."}
    hh, hl = highs[1] > highs[0], lows[1] > lows[0]
    if hh and hl:
        return {"trend": "up", "text": "Higher highs and higher lows: uptrend in this range."}
    if not hh and not hl:
        return {"trend": "down", "text": "Lower highs and lower lows: downtrend in this range."}
    if hh and not hl:
        return {"trend": "mixed", "text": "Higher high but lower low: swings are widening, no clear trend."}
    return {"trend": "sideways", "text": "Lower high but higher low: price is squeezing sideways."}


def market_highlights(price: float, hourly: list[dict], daily: list[dict], t24: dict) -> list[dict]:
    """Return a list of {level, title, detail}. level: info | watch | alert."""
    out: list[dict] = []
    closes_d = [k["c"] for k in daily]

    # 1. How much it moved today, compared with a normal day
    chg24 = float(t24.get("priceChangePercent", 0))
    ranges = [(k["h"] - k["l"]) / k["l"] * 100 for k in daily[-15:-1]] if len(daily) > 2 else []
    normal = sum(ranges) / len(ranges) if ranges else 0
    hi, lo = float(t24.get("highPrice", price)), float(t24.get("lowPrice", price))
    today_range = (hi - lo) / lo * 100 if lo else 0
    ratio = today_range / normal if normal else 1
    level = "alert" if ratio >= 2 else "watch" if ratio >= 1.4 else "info"
    out.append({
        "level": level,
        "title": f"{'Up' if chg24 >= 0 else 'Down'} {abs(chg24):.2f}% in 24h",
        "detail": (f"Today's range is {today_range:.1f}%, about {ratio:.1f}x a normal day ({normal:.1f}%). "
                   + ("Unusually big swings: prices can whip both ways, so wider stops or smaller size."
                      if ratio >= 1.4 else "A fairly normal day for BTC.")),
    })

    # 2. Last hour
    if len(hourly) >= 2:
        h1 = pct(price, hourly[-2]["c"])
        if abs(h1) >= 1:
            out.append({"level": "watch", "title": f"{'Jumped' if h1 > 0 else 'Dropped'} {abs(h1):.1f}% in the last hour",
                        "detail": "Fast moves pull people into emotional trades. Wait for the move to settle before acting."})

    # 3. Where it sits in today's range
    if hi > lo:
        where = (price - lo) / (hi - lo) * 100
        if where >= 85:
            out.append({"level": "watch", "title": "Near today's high",
                        "detail": f"Price is {where:.0f}% of the way up today's range ({lo:,.0f} to {hi:,.0f}). Buying here means buying after the rise."})
        elif where <= 15:
            out.append({"level": "watch", "title": "Near today's low",
                        "detail": f"Price is near the bottom of today's range ({lo:,.0f} to {hi:,.0f}). Lows can break further; a dip is not automatically a bargain."})

    # 4. Trend against moving averages (daily candles)
    ma7, ma25, ma99 = sma(closes_d, 7), sma(closes_d, 25), sma(closes_d, 99)
    if ma25 and ma99:
        if price > ma25 > ma99:
            trend = ("info", "Longer-term uptrend", "Price is above its 25-day and 99-day averages, and the 25 is above the 99.")
        elif price < ma25 < ma99:
            trend = ("alert", "Longer-term downtrend", "Price is below its 25-day and 99-day averages. Buying in a downtrend is swimming against the current.")
        elif price < ma25 and price > ma99:
            trend = ("watch", "Pullback inside an uptrend", f"Below the 25-day average ({ma25:,.0f}) but still above the 99-day ({ma99:,.0f}). The bigger trend is intact, the short-term one is weak.")
        else:
            trend = ("watch", "Mixed trend", "The averages disagree, so there's no clear direction. Clear setups are easier to trade than mixed ones.")
        out.append({"level": trend[0], "title": trend[1], "detail": trend[2],
                    "values": {"ma7": ma7, "ma25": ma25, "ma99": ma99}})

    # 5. Streak of red or green days
    if len(daily) >= 4:
        streak, color = 0, None
        for k in reversed(daily[:-1]):
            c = "green" if k["c"] >= k["o"] else "red"
            if color is None:
                color = c
            if c != color:
                break
            streak += 1
        if streak >= 3:
            out.append({"level": "watch", "title": f"{streak} {color} days in a row",
                        "detail": "Streaks feel like they'll continue forever. They don't, but nobody knows when they end."})

    # 6. Volume vs normal
    if len(daily) >= 8:
        vol_avg = sum(k["v"] for k in daily[-8:-1]) / 7
        vol_today = float(t24.get("volume", 0))
        if vol_avg and vol_today / vol_avg >= 1.5:
            out.append({"level": "watch", "title": f"Heavy trading: {vol_today / vol_avg:.1f}x normal volume",
                        "detail": "Big volume means many people are acting on something, often news. Find out what before you trade."})
    return out

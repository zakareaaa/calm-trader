"""Everything the dashboard needs, in one place. The web layer (main.py) only
translates HTTP to these calls, so this logic is easy to test."""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from .binance_client import BinanceClient, floor_to_step
from .checks import Context, OrderIdea, review_order
from .insights import describe_structure, find_swings, market_highlights, moving_average, sma
from .journal import Journal
from .mentor import CHECKLIST, mentor_notes
from .portfolio import build_position

CHART_RANGES = {"1D": ("15m", 96), "1W": ("1h", 168), "3M": ("1d", 90), "1Y": ("1d", 365)}
SWING_WINDOW = {"1D": 4, "1W": 6, "3M": 3, "1Y": 8}   # candles on each side that must be lower/higher

ORDER_LABELS = {
    "LIMIT_MAKER": "Take-profit",
    "STOP_LOSS_LIMIT": "Stop-loss",
    "STOP_LOSS": "Stop-loss",
    "TAKE_PROFIT_LIMIT": "Take-profit (trigger)",
    "TAKE_PROFIT": "Take-profit (trigger)",
    "LIMIT": "Limit",
}


class TradeRejected(Exception):
    def __init__(self, message: str, review: dict | None = None):
        super().__init__(message)
        self.review = review


def _day_start_ms() -> int:
    today = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp() * 1000)


class TraderService:
    def __init__(self, client: BinanceClient, journal: Journal, symbol: str = "BTCUSDT",
                 base: str = "BTC", quote: str = "USDT"):
        self.client, self.journal = client, journal
        self.symbol, self.base, self.quote = symbol, base, quote

    # ---------- snapshot ----------
    def _snapshot(self) -> dict:
        c = self.client
        price = c.ticker_price(self.symbol)
        t24 = c.ticker_24h(self.symbol)
        acct = c.account()
        bal = {b["asset"]: (float(b["free"]), float(b["locked"])) for b in acct.get("balances", [])}
        rates = acct.get("commissionRates") or {}
        taker = float(rates.get("taker", 0.001))
        trades = c.my_trades(self.symbol)
        pos = build_position(trades, self.base, self.quote, _day_start_ms())
        orders = c.open_orders(self.symbol)
        f = c.filters(self.symbol)
        usdt_free, usdt_locked = bal.get(self.quote, (0.0, 0.0))
        base_free, base_locked = bal.get(self.base, (0.0, 0.0))
        account_value = usdt_free + usdt_locked + (base_free + base_locked) * price
        return dict(price=price, t24=t24, pos=pos, trades=trades, orders=orders, filters=f, fee=taker,
                    usdt_free=usdt_free, usdt_locked=usdt_locked, base_free=base_free,
                    base_locked=base_locked, account_value=account_value)

    def _highlights(self, price: float, t24: dict) -> list[dict]:
        hourly = self.client.klines(self.symbol, "1h", 48)
        daily = self.client.klines(self.symbol, "1d", 120)
        return market_highlights(price, hourly, daily, t24)

    @staticmethod
    def _order_view(o: dict) -> dict:
        in_plan = o.get("orderListId", -1) != -1
        label = ORDER_LABELS.get(o["type"], o["type"].replace("_", " ").title())
        if o["side"] == "BUY":
            label = "Buy " + label.lower()
        elif in_plan:
            label += " (exit plan)"
        return {
            "orderId": o["orderId"], "label": label, "side": o["side"], "type": o["type"],
            "price": float(o["price"]), "stopPrice": float(o.get("stopPrice") or 0),
            "qty": float(o["origQty"]), "filled": float(o["executedQty"]),
            "time": o.get("time"), "inPlan": in_plan,
        }

    def state(self) -> dict:
        s = self._snapshot()
        price, pos, fee = s["price"], s["pos"], s["fee"]
        highlights = self._highlights(price, s["t24"])
        orders = [self._order_view(o) for o in s["orders"]]
        has_exit = any(o["side"] == "SELL" for o in orders)
        held_value = (s["base_free"] + s["base_locked"]) * price
        position = None
        if pos.qty > 0:
            value_now = pos.value_if_sold(price, fee)
            position = {
                "qty": pos.qty, "avg_price": pos.avg_price, "cost": pos.cost,
                "break_even": pos.break_even(fee), "value_if_sold": value_now,
                "pnl": value_now - pos.cost, "pnl_pct": (value_now / pos.cost - 1) * 100 if pos.cost else 0,
                "untracked_qty": max(0.0, s["base_free"] + s["base_locked"] - pos.qty),
            }
        notes = mentor_notes(
            has_position=pos.qty * price > float(s["filters"]["minNotional"]),
            has_exit_order=has_exit, recent_sells=pos.sells, trades_today=pos.trades_today,
            highlights=highlights,
            position_pct=held_value / s["account_value"] * 100 if s["account_value"] else 0)
        wins = [x for x in pos.sells if x["pnl"] > 0]
        return {
            "mode": "DEMO", "symbol": self.symbol, "base": self.base, "quote": self.quote,
            "price": price,
            "change24": float(s["t24"].get("priceChangePercent", 0)),
            "high24": float(s["t24"].get("highPrice", 0)), "low24": float(s["t24"].get("lowPrice", 0)),
            "fee": fee,
            "balances": {"usdt_free": s["usdt_free"], "usdt_locked": s["usdt_locked"],
                         "base_free": s["base_free"], "base_locked": s["base_locked"]},
            "account_value": s["account_value"],
            "position": position,
            "realized": pos.realized,
            "stats": {"sells": len(pos.sells), "wins": len(wins), "trades_today": pos.trades_today,
                      "fees_paid": pos.fees_paid},
            "open_orders": orders,
            "highlights": highlights,
            "mentor": notes,
            "checklist": [{"title": t, "detail": d} for t, d in CHECKLIST],
            "min_notional": float(s["filters"]["minNotional"]),
        }

    def price(self) -> dict:
        book = self.client.book_ticker(self.symbol)
        mid = (book["bid"] + book["ask"]) / 2
        return {"price": self.client.ticker_price(self.symbol), **book,
                "spread": book["ask"] - book["bid"],
                "spread_pct": (book["ask"] - book["bid"]) / mid * 100 if mid else 0}

    def chart(self, rng: str) -> dict:
        interval, limit = CHART_RANGES.get(rng, CHART_RANGES["1D"])
        daily = interval == "1d"
        # daily ranges fetch 99 extra days so the 99-day average exists from the first point
        kl = self.client.klines(self.symbol, interval, min(limit + (99 if daily else 0), 1000))
        ma25 = ma99 = None
        if daily:
            closes = [k["c"] for k in kl]
            ma25 = moving_average(closes, 25)[-limit:]
            ma99 = moving_average(closes, 99)[-limit:]
            ma_now = {"ma25": ma25[-1], "ma99": ma99[-1]}
        else:
            # intraday ranges can't draw a 25-day line, so send today's values to show as flat levels
            closes = [k["c"] for k in self.client.klines(self.symbol, "1d", 99)]
            ma_now = {"ma25": sma(closes, 25), "ma99": sma(closes, 99)}
        kl = kl[-limit:]
        start = kl[0]["t"] if kl else 0
        trades = self.client.my_trades(self.symbol)
        markers = [{"t": t["time"], "price": float(t["price"]), "side": "buy" if t["isBuyer"] else "sell",
                    "qty": float(t["qty"])} for t in trades if t["time"] >= start]
        k = SWING_WINDOW.get(rng, 4)
        swings = find_swings(kl, k)
        return {"range": rng, "interval": interval,
                "points": [{"t": p["t"], "c": p["c"], "h": p["h"], "l": p["l"]} for p in kl],
                "ma25": ma25, "ma99": ma99, "ma_now": ma_now,
                "swings": swings[-8:], "structure": describe_structure(swings),
                "markers": markers}

    # ---------- orders ----------
    def _context(self, s: dict) -> Context:
        trend = next((h["level"] for h in self._highlights(s["price"], s["t24"]) if "values" in h), "info")
        return Context(price_now=s["price"], position=s["pos"], base_free=s["base_free"],
                       usdt_free=s["usdt_free"], account_value=s["account_value"], buy_fee=s["fee"],
                       sell_fee=s["fee"], min_notional=float(s["filters"]["minNotional"]),
                       chg24=float(s["t24"].get("priceChangePercent", 0)), trend_level=trend,
                       trades_today=s["pos"].trades_today)

    def _review(self, idea: OrderIdea, s: dict):
        review = review_order(idea, self._context(s))
        if not idea.kind.startswith("buy") and s["base_locked"] > 0:
            if s["base_free"] * s["price"] < float(s["filters"]["minNotional"]):
                review.add("block", "Your BTC is locked in open sell orders. Cancel them first (Open orders panel), then place the new one.")
        return review

    def review(self, idea: dict) -> dict:
        o = OrderIdea(**idea)
        s = self._snapshot()
        r = self._review(o, s)
        return {"checks": r.checks, "numbers": r.numbers, "blocked": r.blocked, "needs_ack": r.needs_ack}

    def place(self, idea: dict, acknowledged: bool, confidence: int | None = None, feeling: str | None = None) -> dict:
        o = OrderIdea(**idea)
        s = self._snapshot()
        r = self._review(o, s)
        rv = {"checks": r.checks, "numbers": r.numbers}
        if r.blocked:
            raise TradeRejected("This order has a problem that needs fixing first.", rv)
        if r.needs_ack and not acknowledged:
            raise TradeRejected("Tick 'I understand the warnings' to continue.", rv)

        f, c, sym = s["filters"], self.client, self.symbol
        step, tick = f["stepSize"], f["tickSize"]
        results, notes = [], []

        def p(x: float) -> Decimal:
            return floor_to_step(x, tick)

        if o.kind == "buy_market":
            res = c.market_buy_quote(sym, floor_to_step(o.amount_usdt, "0.01"))
            results.append(res)
            if o.take_profit or o.stop_loss:
                got = Decimal(res.get("executedQty", "0"))
                for fill in res.get("fills", []):
                    if fill.get("commissionAsset") == self.base:
                        got -= Decimal(fill["commission"])
                free_now = Decimal(str(next((float(b["free"]) for b in c.account()["balances"] if b["asset"] == self.base), 0)))
                qty = floor_to_step(min(got, free_now), step)
                results.append(self._place_exit(qty, o.take_profit, o.stop_loss, p))
        elif o.kind == "buy_limit":
            qty = floor_to_step(o.amount_usdt / o.price, step)
            results.append(c.limit_order(sym, "BUY", qty, p(o.price)))
            if o.take_profit or o.stop_loss:
                notes.append("Your exit plan can't be attached until the buy fills. Once it does, set it from the Sell tab (Exit plan).")
        else:
            qty = floor_to_step(s["base_free"] * o.sell_pct / 100, step)
            if o.kind == "sell_market":
                results.append(c.market_sell(sym, qty))
            elif o.kind == "sell_limit":
                results.append(c.limit_order(sym, "SELL", qty, p(o.price)))
            elif o.kind == "exit_plan":
                results.append(self._place_exit(qty, o.take_profit, o.stop_loss, p))
            else:
                raise TradeRejected(f"Unknown order type {o.kind}")

        ref = ",".join(str(x.get("orderId") or x.get("orderListId")) for x in results)
        self.journal.add(symbol=sym, kind=o.kind, amount_usdt=o.amount_usdt, sell_pct=o.sell_pct,
                         price=o.price or s["price"], take_profit=o.take_profit, stop_loss=o.stop_loss,
                         reason=o.reason.strip(), confidence=confidence, feeling=feeling,
                         order_ref=ref, status="sent", warnings=json.dumps([x["msg"] for x in r.checks if x["level"] == "warn"]))
        return {"ok": True, "orders": results, "notes": notes}

    def _place_exit(self, qty: Decimal, tp: float, sl: float, p) -> dict:
        c, sym = self.client, self.symbol
        if tp and sl:
            return c.oco_sell(sym, qty, p(tp), p(sl), p(sl * 0.999))
        if tp:
            return c.limit_order(sym, "SELL", qty, p(tp))
        return c.stop_loss_sell(sym, qty, p(sl), p(sl * 0.999))

    def cancel(self, order_id: int) -> dict:
        return self.client.cancel_order(self.symbol, order_id)

    # ---------- journal ----------
    def journal_list(self) -> list[dict]:
        return self.journal.list()

    def journal_review(self, entry_id: int, text: str) -> None:
        self.journal.set_review(entry_id, text)

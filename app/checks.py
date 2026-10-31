"""Pre-trade checks: the questions a careful mentor asks before every order.

Each check returns a level:
  block -> the order would be wrong or impossible; it won't be sent
  warn  -> allowed, but you must tick "I understand" first
  info  -> worth knowing
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .portfolio import Position

MAX_RISK_PCT = 2.0      # max loss per trade as % of the whole account
MAX_SIZE_PCT = 25.0     # max size of one buy as % of the whole account
OVERTRADING = 5         # trades per day before we slow you down


@dataclass
class OrderIdea:
    kind: str                       # buy_market | buy_limit | sell_market | sell_limit | exit_plan
    amount_usdt: float = 0.0        # buys
    sell_pct: float = 100.0         # sells / exit plan: % of your coins
    price: float = 0.0              # limit price
    take_profit: float = 0.0        # optional on buys, required for exit_plan
    stop_loss: float = 0.0          # trigger price
    reason: str = ""


@dataclass
class Context:
    price_now: float
    position: Position
    base_free: float
    usdt_free: float
    account_value: float
    buy_fee: float
    sell_fee: float
    min_notional: float
    chg24: float
    trend_level: str                # info | watch | alert (from insights)
    trades_today: int


@dataclass
class Review:
    checks: list[dict] = field(default_factory=list)
    numbers: dict = field(default_factory=dict)

    def add(self, level: str, msg: str):
        self.checks.append({"level": level, "msg": msg})

    @property
    def blocked(self) -> bool:
        return any(c["level"] == "block" for c in self.checks)

    @property
    def needs_ack(self) -> bool:
        return any(c["level"] == "warn" for c in self.checks)


def review_order(o: OrderIdea, c: Context) -> Review:
    r = Review()
    pos = c.position
    if not o.reason.strip():
        r.add("block", "Write down why you're making this trade. If you can't explain it in one sentence, don't make it.")

    if o.kind.startswith("buy"):
        _review_buy(o, c, r, pos)
    else:
        _review_sell(o, c, r, pos)
    if c.trades_today >= OVERTRADING:
        r.add("warn", f"This would be trade #{c.trades_today + 1} today. More trades mostly means more fees and more emotional decisions.")
    return r


def _review_buy(o: OrderIdea, c: Context, r: Review, pos: Position):
    entry = o.price if o.kind == "buy_limit" and o.price > 0 else c.price_now
    amt = o.amount_usdt
    if amt <= 0:
        r.add("block", "Enter how much USDT to spend.")
        return
    if amt < c.min_notional:
        r.add("block", f"Binance's minimum order is {c.min_notional:g} USDT.")
    if amt > c.usdt_free + 1e-9:
        r.add("block", f"You only have {c.usdt_free:,.2f} USDT available.")
    if o.kind == "buy_limit":
        if o.price <= 0:
            r.add("block", "Enter the price you want to buy at.")
            return
        if o.price > c.price_now * 1.001:
            r.add("warn", f"Your buy price is above the current price ({c.price_now:,.2f}). It will fill right away, like a market order, at the current price.")
    else:
        r.add("info", "Market order: fills now at the best sellers' prices, and you pay the taker fee.")

    qty = amt / entry * (1 - c.buy_fee)
    new_qty, new_cost = pos.qty + qty, pos.cost + amt
    be_after = new_cost / (new_qty * (1 - c.sell_fee))
    trade_be = entry / ((1 - c.buy_fee) * (1 - c.sell_fee))
    r.numbers.update({"entry": entry, "qty": qty, "trade_break_even": trade_be, "break_even_after": be_after})

    size_pct = amt / c.account_value * 100 if c.account_value else 100
    if size_pct > MAX_SIZE_PCT:
        r.add("warn", f"This buy is {size_pct:.0f}% of your whole account. Keeping single trades under {MAX_SIZE_PCT:.0f}% means one mistake can't sink you.")

    if o.stop_loss <= 0:
        r.add("warn", "No stop-loss. Decide the price where you admit you're wrong BEFORE you buy, while you're calm.")
    else:
        if o.stop_loss >= entry:
            r.add("block", "Your stop-loss must be below your buy price.")
        else:
            loss = amt - qty * o.stop_loss * (1 - c.sell_fee)
            risk_pct = loss / c.account_value * 100 if c.account_value else 100
            r.numbers.update({"loss_at_stop": loss, "risk_pct": risk_pct})
            level = "warn" if risk_pct > MAX_RISK_PCT else "info"
            r.add(level, f"If the stop hits you lose about {loss:,.2f} USDT, {risk_pct:.2f}% of your account"
                  + (f". Professionals usually risk 1-2% per trade." if level == "warn" else ". That's a sensible size."))

    if o.take_profit > 0:
        gain = qty * o.take_profit * (1 - c.sell_fee) - amt
        r.numbers.update({"gain_at_target": gain})
        if o.take_profit <= trade_be:
            r.add("block", f"Your take-profit ({o.take_profit:,.2f}) is below this trade's break-even after fees ({trade_be:,.2f}). It would lock in a loss.")
        else:
            move = (o.take_profit / entry - 1) * 100
            if move < 1:
                r.add("warn", f"Your target is only a {move:.2f}% move. About 0.2% of that goes to fees, so the reward is small for the risk.")
            if o.stop_loss > 0 and o.stop_loss < entry:
                rr = gain / r.numbers["loss_at_stop"] if r.numbers.get("loss_at_stop") else 0
                r.numbers["reward_risk"] = rr
                if rr < 1:
                    r.add("warn", f"You're risking {r.numbers['loss_at_stop']:,.2f} to make {gain:,.2f} (1 : {rr:.2f}). With odds like that you need to be right most of the time.")
                else:
                    r.add("info", f"Reward to risk is 1 : {rr:.2f}.")

    if c.chg24 >= 5:
        r.add("warn", f"BTC is up {c.chg24:.1f}% in 24h. Buying right after a big jump is how people buy tops. Is this a plan or fear of missing out?")
    if c.trend_level == "alert":
        r.add("warn", "BTC is in a downtrend on the daily chart. Buying now is betting the trend turns.")
    if pos.qty > 0 and entry < pos.avg_price:
        r.add("info", f"You already hold BTC at an average of {pos.avg_price:,.2f}. Buying lower ('averaging down') lowers your break-even to {be_after:,.2f}, but adds to a position that's losing.")


def _review_sell(o: OrderIdea, c: Context, r: Review, pos: Position):
    if not (0 < o.sell_pct <= 100):
        r.add("block", "Choose how much to sell (1-100% of your BTC).")
        return
    qty = c.base_free * o.sell_pct / 100
    price = o.price if o.kind == "sell_limit" else (o.take_profit if o.kind == "exit_plan" else c.price_now)
    r.numbers.update({"qty": qty})
    if qty * (price or c.price_now) < c.min_notional:
        r.add("block", f"That's below Binance's {c.min_notional:g} USDT minimum.")
    be = pos.break_even(c.sell_fee)

    if o.kind == "sell_limit":
        if o.price <= 0:
            r.add("block", "Enter the price you want to sell at.")
            return
        if o.price < c.price_now * 0.999:
            r.add("warn", f"Your sell price is below the current price ({c.price_now:,.2f}). It will fill right away at the buyers' prices.")
    elif o.kind == "sell_market":
        r.add("info", "Market order: sells now at the best buyers' prices, and you pay the taker fee.")
    elif o.kind == "exit_plan":
        if o.take_profit <= c.price_now:
            r.add("block", f"Take-profit must be above the current price ({c.price_now:,.2f}).")
        if not (0 < o.stop_loss < c.price_now):
            r.add("block", f"Stop-loss must be below the current price ({c.price_now:,.2f}).")
        if 0 < o.stop_loss and be and o.take_profit > 0:
            gain = pos.value_if_sold(o.take_profit, c.sell_fee, qty) - pos.avg_price * qty
            loss = pos.avg_price * qty - pos.value_if_sold(o.stop_loss * 0.999, c.sell_fee, qty)
            r.numbers.update({"gain_at_target": gain, "loss_at_stop": loss})
            if loss > 0 and gain > 0 and gain / loss < 1:
                r.add("warn", f"You're risking {loss:,.2f} to make {gain:,.2f}. Consider a closer stop or a further target.")

    if be and price and price < be:
        loss = pos.avg_price * qty - pos.value_if_sold(price, c.sell_fee, qty)
        r.add("info", f"At {price:,.2f} you're below your break-even ({be:,.2f}): selling locks in about {loss:,.2f} USDT of loss. That's fine if your reason to hold is gone.")
    r.numbers.update({"break_even": be})

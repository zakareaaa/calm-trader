"""Turn your trade history into one clear picture of your position.

Binance pools all your BTC into one balance, so we track it the way an
accountant would: average cost. Buys add coins and cost; sells remove coins at
the average cost and the difference is realized profit or loss.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    base: str
    quote: str
    qty: float = 0.0                 # coins held according to trade history
    cost: float = 0.0                # USDT paid for those coins, incl. buy fees
    realized: float = 0.0            # profit/loss already locked in by sells
    sells: list[dict] = field(default_factory=list)  # one entry per sell, for the journal
    fees_paid: float = 0.0           # in quote currency where we can tell
    trades_today: int = 0

    @property
    def avg_price(self) -> float:
        return self.cost / self.qty if self.qty > 0 else 0.0

    def break_even(self, sell_fee: float) -> float:
        """Price to sell everything at to get back exactly what you paid."""
        if self.qty <= 0:
            return 0.0
        return self.cost / (self.qty * (1 - sell_fee))

    def target_price(self, profit: float, sell_fee: float) -> float:
        if self.qty <= 0:
            return 0.0
        return (self.cost + profit) / (self.qty * (1 - sell_fee))

    def value_if_sold(self, price: float, sell_fee: float, qty: float | None = None) -> float:
        q = self.qty if qty is None else qty
        return q * price * (1 - sell_fee)


def build_position(trades: list[dict], base: str, quote: str, day_start_ms: int = 0) -> Position:
    pos = Position(base=base, quote=quote)
    for t in sorted(trades, key=lambda x: (x["time"], x["id"])):
        qty, quote_qty = float(t["qty"]), float(t["quoteQty"])
        fee, fee_asset = float(t["commission"]), t["commissionAsset"]
        if t["time"] >= day_start_ms:
            pos.trades_today += 1
        if t["isBuyer"]:
            got = qty - fee if fee_asset == base else qty
            paid = quote_qty + (fee if fee_asset == quote else 0.0)
            if fee_asset == base:
                pos.fees_paid += fee * float(t["price"])
            elif fee_asset == quote:
                pos.fees_paid += fee
            pos.qty += got
            pos.cost += paid
        else:
            if pos.qty <= 0:
                continue  # sold coins we have no history for; ignore for cost tracking
            q = min(qty, pos.qty)
            cost_out = pos.avg_price * q
            proceeds = quote_qty - (fee if fee_asset == quote else 0.0)
            if fee_asset == quote:
                pos.fees_paid += fee
            pnl = proceeds - cost_out
            pos.realized += pnl
            pos.sells.append({"time": t["time"], "price": float(t["price"]), "qty": q, "pnl": pnl,
                              "pct": pnl / cost_out * 100 if cost_out else 0.0})
            pos.qty -= q
            pos.cost -= cost_out
            if pos.qty < 1e-12:
                pos.qty, pos.cost = 0.0, 0.0
    return pos

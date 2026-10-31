"""An in-memory stand-in for Binance, so the app can be tested without a network."""
from __future__ import annotations

import math
import time
from decimal import Decimal


def make_klines(n: int, start: float, step_ms: int, drift: float = 0.0, wave: float = 3):
    now = int(time.time() * 1000)
    out, price = [], start
    for i in range(n):
        o = price
        price = price * (1 + drift + 0.006 * math.sin(i / wave) + 0.003 * math.sin(i / 1.7))
        out.append({"t": now - (n - i) * step_ms, "o": o, "h": max(o, price) * 1.004,
                    "l": min(o, price) * 0.996, "c": price, "v": 20000 + 3000 * math.sin(i)})
    return out


class FakeBinance:
    def __init__(self, price: float = 77300.0):
        self.price = price
        self.usdt = 4848.13
        self.btc = 0.00195744
        self.btc_locked = 0.0
        now = int(time.time() * 1000)
        self.trades = [
            {"id": 1, "time": now - 3_600_000 * 20, "price": "77660.01", "qty": "0.00064", "quoteQty": "49.7024064",
             "commission": "0.00000064", "commissionAsset": "BTC", "isBuyer": True},
            {"id": 2, "time": now - 3_600_000 * 19, "price": "77688.00", "qty": "0.00060", "quoteQty": "46.6128",
             "commission": "0.0466128", "commissionAsset": "USDT", "isBuyer": False},
            {"id": 3, "time": now - 3_600_000 * 18, "price": "77653.22", "qty": "0.00064", "quoteQty": "49.6980608",
             "commission": "0.00000064", "commissionAsset": "BTC", "isBuyer": True},
            {"id": 4, "time": now - 3_600_000 * 17, "price": "77534.01", "qty": "0.00064", "quoteQty": "49.6217664",
             "commission": "0.00000064", "commissionAsset": "BTC", "isBuyer": True},
            {"id": 5, "time": now - 3_600_000 * 15, "price": "77209.10", "qty": "0.00064", "quoteQty": "49.413824",
             "commission": "0.00000064", "commissionAsset": "BTC", "isBuyer": True},
        ]
        self.orders: list[dict] = []
        self.calls: list[tuple] = []
        self._next_id = 100

    def sync_time(self):
        pass

    def ticker_price(self, symbol):
        return self.price

    def book_ticker(self, symbol):
        return {"bid": self.price - 0.01, "ask": self.price, "bid_qty": 1.2, "ask_qty": 0.8}

    def ticker_24h(self, symbol):
        return {"priceChangePercent": "-5.02", "highPrice": "81967.21", "lowPrice": "76501.00", "volume": "34316.08"}

    def klines(self, symbol, interval, limit=100):
        step = {"15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}[interval]
        drift = 0.002 if interval == "1d" else 0.0
        kl = make_klines(limit, self.price / ((1 + drift) ** limit), step, drift, wave=11 if interval == "1d" else 3)
        kl[-1]["c"] = self.price
        return kl

    def filters(self, symbol):
        return {"tickSize": Decimal("0.01"), "stepSize": Decimal("0.00001"),
                "minQty": Decimal("0.00001"), "minNotional": Decimal("5")}

    def account(self):
        return {"commissionRates": {"maker": "0.00100000", "taker": "0.00100000"},
                "balances": [{"asset": "USDT", "free": str(self.usdt), "locked": "0"},
                             {"asset": "BTC", "free": f"{self.btc:.8f}", "locked": f"{self.btc_locked:.8f}"}]}

    def my_trades(self, symbol, limit=1000):
        return list(self.trades)

    def open_orders(self, symbol):
        return list(self.orders)

    def _order(self, side, type_, qty, price="0", stop="0", list_id=-1):
        self._next_id += 1
        o = {"orderId": self._next_id, "orderListId": list_id, "side": side, "type": type_,
             "price": str(price), "stopPrice": str(stop), "origQty": str(qty), "executedQty": "0",
             "time": int(time.time() * 1000)}
        return o

    def market_buy_quote(self, symbol, usdt):
        self.calls.append(("market_buy_quote", usdt))
        qty = Decimal(usdt) / Decimal(str(self.price))
        qty = qty.quantize(Decimal("0.00001"), rounding="ROUND_DOWN")
        fee = qty * Decimal("0.001")
        self.usdt -= float(usdt)
        self.btc += float(qty - fee)
        return {"orderId": 999, "executedQty": str(qty),
                "fills": [{"price": str(self.price), "qty": str(qty), "commission": str(fee), "commissionAsset": "BTC"}]}

    def market_sell(self, symbol, qty):
        self.calls.append(("market_sell", qty))
        return {"orderId": 998}

    def limit_order(self, symbol, side, qty, price):
        self.calls.append(("limit_order", side, qty, price))
        o = self._order(side, "LIMIT", qty, price)
        self.orders.append(o)
        return o

    def stop_loss_sell(self, symbol, qty, stop_trigger, stop_limit):
        self.calls.append(("stop_loss_sell", qty, stop_trigger, stop_limit))
        o = self._order("SELL", "STOP_LOSS_LIMIT", qty, stop_limit, stop_trigger)
        self.orders.append(o)
        return o

    def oco_sell(self, symbol, qty, take_profit, stop_trigger, stop_limit):
        self.calls.append(("oco_sell", qty, take_profit, stop_trigger, stop_limit))
        self.orders.append(self._order("SELL", "LIMIT_MAKER", qty, take_profit, list_id=7))
        self.orders.append(self._order("SELL", "STOP_LOSS_LIMIT", qty, stop_limit, stop_trigger, list_id=7))
        self.btc_locked, self.btc = self.btc_locked + float(qty), self.btc - float(qty)
        return {"orderListId": 7}

    def cancel_order(self, symbol, order_id):
        self.calls.append(("cancel_order", order_id))
        target = next(o for o in self.orders if o["orderId"] == order_id)
        lid = target["orderListId"]
        self.orders = [o for o in self.orders if o["orderId"] != order_id and (lid == -1 or o["orderListId"] != lid)]
        return {"orderId": order_id, "status": "CANCELED"}

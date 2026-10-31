"""Small, explicit client for the Binance Spot REST API (Demo Mode only).

Every signed request is HMAC-SHA256 signed with your API secret, exactly as
described in Binance's "SIGNED endpoint security" docs. The client refuses to
talk to anything except the demo host, so a live key can never be used by
accident.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from decimal import ROUND_DOWN, Decimal
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

DEMO_HOST = "demo-api.binance.com"


class BinanceError(Exception):
    """An error returned by Binance (bad price, insufficient balance, ...)."""

    def __init__(self, status: int, code: int | None, msg: str):
        super().__init__(f"Binance error {code}: {msg}")
        self.status = status
        self.code = code
        self.msg = msg


def fmt_decimal(value: Decimal | float | str) -> str:
    """Binance wants plain decimal strings: no exponent, no trailing zeros."""
    d = Decimal(str(value))
    s = format(d.normalize(), "f")
    return s


def floor_to_step(value: Decimal | float | str, step: Decimal | str) -> Decimal:
    """Round DOWN to the exchange's step size (LOT_SIZE / PRICE_FILTER)."""
    v, s = Decimal(str(value)), Decimal(str(step))
    if s == 0:
        return v
    return (v / s).to_integral_value(rounding=ROUND_DOWN) * s


class BinanceClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = f"https://{DEMO_HOST}",
        session: requests.Session | None = None,
        recv_window: int = 5000,
    ):
        host = urlparse(base_url).hostname
        if host != DEMO_HOST:
            raise ValueError(
                f"Refusing to use {host!r}. This app only trades on Binance Demo "
                f"({DEMO_HOST}) for now."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.session = session or requests.Session()
        self.recv_window = recv_window
        self._time_offset_ms = 0
        self._filters: dict[str, dict[str, Decimal]] = {}

    # ---------- low level ----------
    def _sign(self, query: str) -> str:
        return hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, signed: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {}
        if signed:
            if not self.api_key or not self.api_secret:
                raise BinanceError(401, None, "API key/secret missing. Add them to your .env file.")
            params["recvWindow"] = self.recv_window
            params["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
            query = urlencode(params)
            query += "&signature=" + self._sign(query)
            headers["X-MBX-APIKEY"] = self.api_key
        else:
            query = urlencode(params)
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        resp = self.session.request(method, url, headers=headers, timeout=10)
        try:
            data = resp.json()
        except ValueError:
            data = {"msg": resp.text}
        if resp.status_code >= 400:
            raise BinanceError(resp.status_code, data.get("code"), data.get("msg", "Unknown error"))
        return data

    def sync_time(self) -> None:
        """Avoid 'Timestamp outside recvWindow' errors if your clock drifts."""
        server = self._request("GET", "/api/v3/time")["serverTime"]
        self._time_offset_ms = int(server) - int(time.time() * 1000)

    # ---------- market data (public) ----------
    def ticker_price(self, symbol: str) -> float:
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def book_ticker(self, symbol: str) -> dict:
        """Best bid and best ask right now."""
        d = self._request("GET", "/api/v3/ticker/bookTicker", {"symbol": symbol})
        return {"bid": float(d["bidPrice"]), "ask": float(d["askPrice"]),
                "bid_qty": float(d["bidQty"]), "ask_qty": float(d["askQty"])}

    def ticker_24h(self, symbol: str) -> dict:
        return self._request("GET", "/api/v3/ticker/24hr", {"symbol": symbol})

    def klines(self, symbol: str, interval: str, limit: int = 100) -> list[dict]:
        rows = self._request("GET", "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return [
            {"t": r[0], "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])}
            for r in rows
        ]

    def filters(self, symbol: str) -> dict[str, Decimal]:
        """tickSize, stepSize, minQty, minNotional for a symbol (cached)."""
        if symbol not in self._filters:
            info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
            f = {x["filterType"]: x for x in info["symbols"][0]["filters"]}
            notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
            self._filters[symbol] = {
                "tickSize": Decimal(f["PRICE_FILTER"]["tickSize"]),
                "stepSize": Decimal(f["LOT_SIZE"]["stepSize"]),
                "minQty": Decimal(f["LOT_SIZE"]["minQty"]),
                "minNotional": Decimal(notional.get("minNotional", "5")),
            }
        return self._filters[symbol]

    # ---------- account (signed) ----------
    def account(self) -> dict:
        return self._request("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)

    def my_trades(self, symbol: str, limit: int = 1000) -> list[dict]:
        return self._request("GET", "/api/v3/myTrades", {"symbol": symbol, "limit": limit}, signed=True)

    def open_orders(self, symbol: str) -> list[dict]:
        return self._request("GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True)

    # ---------- trading (signed) ----------
    def market_buy_quote(self, symbol: str, usdt: Decimal) -> dict:
        """Buy with a USDT amount ("spend 50 USDT")."""
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": fmt_decimal(usdt), "newOrderRespType": "FULL",
        }, signed=True)

    def market_sell(self, symbol: str, qty: Decimal) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": fmt_decimal(qty), "newOrderRespType": "FULL",
        }, signed=True)

    def limit_order(self, symbol: str, side: str, qty: Decimal, price: Decimal) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
            "quantity": fmt_decimal(qty), "price": fmt_decimal(price),
        }, signed=True)

    def stop_loss_sell(self, symbol: str, qty: Decimal, stop_trigger: Decimal, stop_limit: Decimal) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "STOP_LOSS_LIMIT", "timeInForce": "GTC",
            "quantity": fmt_decimal(qty), "stopPrice": fmt_decimal(stop_trigger), "price": fmt_decimal(stop_limit),
        }, signed=True)

    def oco_sell(self, symbol: str, qty: Decimal, take_profit: Decimal,
                 stop_trigger: Decimal, stop_limit: Decimal) -> dict:
        """Take-profit (LIMIT_MAKER above) + stop-loss (STOP_LOSS_LIMIT below)."""
        return self._request("POST", "/api/v3/orderList/oco", {
            "symbol": symbol, "side": "SELL", "quantity": fmt_decimal(qty),
            "aboveType": "LIMIT_MAKER", "abovePrice": fmt_decimal(take_profit),
            "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": fmt_decimal(stop_trigger),
            "belowPrice": fmt_decimal(stop_limit), "belowTimeInForce": "GTC",
        }, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancelling one leg of an OCO cancels the whole pair."""
        return self._request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

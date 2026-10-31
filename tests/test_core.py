import hashlib
import hmac
from decimal import Decimal

import pytest

from app.binance_client import BinanceClient, floor_to_step, fmt_decimal
from app.checks import Context, OrderIdea, review_order
from app.journal import Journal
from app.portfolio import build_position
from app.service import TradeRejected, TraderService
from tests.fakes import FakeBinance


# ---------- client ----------
def test_refuses_live_host():
    with pytest.raises(ValueError):
        BinanceClient("k", "s", base_url="https://api.binance.com")


def test_signature_matches_binance_doc_example():
    # Example from Binance's "SIGNED endpoint" docs (HMAC section)
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    query = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
             "&recvWindow=5000&timestamp=1499827319559")
    c = BinanceClient("key", secret)
    assert c._sign(query) == hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    assert c._sign(query) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_rounding_helpers():
    assert floor_to_step("0.001957", "0.00001") == Decimal("0.00195")
    assert fmt_decimal(Decimal("80225.4400")) == "80225.44"
    assert fmt_decimal(1e-05) == "0.00001"


# ---------- portfolio ----------
def test_position_average_cost_and_break_even():
    fb = FakeBinance()
    pos = build_position(fb.my_trades("BTCUSDT"), "BTC", "USDT")
    # first round: bought 0.00063936 net, sold 0.0006 -> about -0.08 realized
    assert pos.sells and -0.12 < pos.sells[0]["pnl"] < -0.05
    assert abs(pos.qty - (0.00063936 - 0.0006 + 3 * 0.00063936)) < 1e-10
    be = pos.break_even(0.001)
    assert 77500 < be < 77700
    # selling exactly at break-even returns the cost
    assert abs(pos.value_if_sold(be, 0.001) - pos.cost) < 1e-9


# ---------- checks ----------
def ctx(**kw):
    fb = FakeBinance()
    base = dict(price_now=77300, position=build_position(fb.trades, "BTC", "USDT"), base_free=0.00195744,
                usdt_free=4848.13, account_value=5000, buy_fee=0.001, sell_fee=0.001, min_notional=5,
                chg24=-5, trend_level="watch", trades_today=1)
    base.update(kw)
    return Context(**base)


def levels(r):
    return [c["level"] for c in r.checks]


def test_reason_is_required():
    r = review_order(OrderIdea(kind="buy_market", amount_usdt=50), ctx())
    assert r.blocked


def test_take_profit_below_break_even_is_blocked():
    r = review_order(OrderIdea(kind="buy_market", amount_usdt=50, take_profit=77350, stop_loss=76000, reason="x"), ctx())
    assert r.blocked
    assert any("below this trade's break-even" in c["msg"] for c in r.checks)


def test_good_plan_passes_with_info_only():
    r = review_order(OrderIdea(kind="buy_market", amount_usdt=50, take_profit=80000, stop_loss=76000, reason="pullback in uptrend"), ctx())
    assert not r.blocked and r.numbers["reward_risk"] > 1


def test_no_stop_and_big_size_warn():
    r = review_order(OrderIdea(kind="buy_market", amount_usdt=2000, reason="x"), ctx())
    msgs = " ".join(c["msg"] for c in r.checks)
    assert r.needs_ack and "No stop-loss" in msgs and "of your whole account" in msgs


def test_exit_plan_direction_rules():
    r = review_order(OrderIdea(kind="exit_plan", take_profit=77000, stop_loss=78000, reason="x"), ctx())
    assert r.blocked


# ---------- trend tools ----------
from app.insights import describe_structure, find_swings, moving_average


def pts(prices):
    return [{"t": i, "h": p + 1, "l": p - 1, "c": p} for i, p in enumerate(prices)]


def test_moving_average():
    ma = moving_average([1, 2, 3, 4, 5], 3)
    assert ma[:2] == [None, None] and ma[2:] == [2, 3, 4]


def test_uptrend_structure():
    prices = [10, 12, 14, 12, 11, 13, 16, 18, 15, 14, 16, 20, 22, 19, 17, 19, 21, 24, 26, 23, 22]
    sw = find_swings(pts(prices), 2)
    kinds = [s["kind"] for s in sw]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))   # alternates H/L
    assert describe_structure(sw)["trend"] == "up"


def test_downtrend_structure():
    prices = [30, 28, 26, 28, 29, 27, 24, 22, 25, 26, 24, 20, 18, 21, 23, 21, 19, 16, 14, 17, 18]
    assert describe_structure(find_swings(pts(prices), 2))["trend"] == "down"


# ---------- service ----------
@pytest.fixture
def svc(tmp_path):
    return TraderService(FakeBinance(), Journal(tmp_path / "j.db"))


def test_state_shape(svc):
    s = svc.state()
    assert s["mode"] == "DEMO" and s["position"]["break_even"] > 0
    assert any(n["title"] == "Your BTC has no exit plan" for n in s["mentor"])
    assert s["highlights"]


def test_price_and_chart_extras(svc):
    p = svc.price()
    assert p["ask"] >= p["bid"] and abs(p["spread"] - 0.01) < 1e-9
    c = svc.chart("3M")
    assert len(c["points"]) == 90 and len(c["ma25"]) == 90 and c["ma99"][0] is not None
    assert c["swings"] and c["structure"]["text"]
    assert svc.chart("1D")["ma25"] is None


def test_buy_with_exit_plan_places_oco_and_journals(svc):
    out = svc.place({"kind": "buy_market", "amount_usdt": 50, "take_profit": 80000, "stop_loss": 76000,
                     "reason": "test"}, acknowledged=True)
    assert out["ok"]
    kinds = [c[0] for c in svc.client.calls]
    assert kinds == ["market_buy_quote", "oco_sell"]
    _, qty, tp, sl, sl_limit = svc.client.calls[1]
    assert tp == Decimal("80000.00") and sl == Decimal("76000.00") and sl_limit < sl
    assert qty <= Decimal("0.00065")
    assert svc.journal_list()[0]["reason"] == "test"


def test_warnings_need_ack(svc):
    with pytest.raises(TradeRejected):
        svc.place({"kind": "buy_market", "amount_usdt": 50, "reason": "no stop"}, acknowledged=False)


def test_locked_coins_block_new_sell_and_cancel_clears_pair(svc):
    svc.place({"kind": "exit_plan", "sell_pct": 100, "take_profit": 80000, "stop_loss": 76000, "reason": "plan"},
              acknowledged=True)
    with pytest.raises(TradeRejected) as e:
        svc.place({"kind": "sell_market", "sell_pct": 100, "reason": "x"}, acknowledged=True)
    assert "locked" in str(e.value.review)
    oid = svc.client.orders[0]["orderId"]
    svc.cancel(oid)
    assert svc.client.orders == []

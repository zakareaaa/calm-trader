"""FastAPI web layer. Run with:  uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .binance_client import BinanceClient, BinanceError
from .journal import Journal
from .service import TradeRejected, TraderService

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

client = BinanceClient(
    api_key=os.getenv("BINANCE_API_KEY", ""),
    api_secret=os.getenv("BINANCE_API_SECRET", ""),
    base_url=os.getenv("BINANCE_BASE_URL", "https://demo-api.binance.com"),
)
JOURNAL_PATH = Path(os.getenv("JOURNAL_PATH") or ROOT / "journal.db")
service = TraderService(client, Journal(JOURNAL_PATH),
                        symbol=os.getenv("SYMBOL", "BTCUSDT"), base=os.getenv("BASE", "BTC"),
                        quote=os.getenv("QUOTE", "USDT"))

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        client.sync_time()
    except Exception:  # noqa: BLE001 - the app still works; Binance will complain if the clock is off
        pass
    yield


app = FastAPI(title="Calm Trader (Demo)", docs_url="/docs", lifespan=lifespan)


def same_app_only(x_calm_trader: str | None = Header(default=None)):
    """Only our own page sends this header. Other websites can't add custom
    headers to requests to localhost without a CORS preflight, which we never
    allow, so they can't place orders through this app."""
    if x_calm_trader != "1":
        raise HTTPException(status_code=403, detail="Requests must come from the Calm Trader page.")


@app.exception_handler(BinanceError)
def _binance_error(_, exc: BinanceError):
    return JSONResponse(status_code=400, content={"detail": f"Binance said: {exc.msg}", "code": exc.code})


@app.exception_handler(TradeRejected)
def _rejected(_, exc: TradeRejected):
    return JSONResponse(status_code=422, content={"detail": str(exc), "review": exc.review})


class Idea(BaseModel):
    kind: str = Field(pattern="^(buy_market|buy_limit|sell_market|sell_limit|exit_plan)$")
    amount_usdt: float = 0
    sell_pct: float = 100
    price: float = 0
    take_profit: float = 0
    stop_loss: float = 0
    reason: str = ""


class PlaceRequest(BaseModel):
    idea: Idea
    acknowledged: bool = False
    confidence: int | None = Field(default=None, ge=1, le=5)
    feeling: str | None = None


class ReviewNote(BaseModel):
    text: str


guard = [Depends(same_app_only)]


@app.get("/api/state", dependencies=guard)
def state():
    return service.state()


@app.get("/api/price", dependencies=guard)
def price():
    return service.price()


@app.get("/api/chart", dependencies=guard)
def chart(range: str = "1D"):  # noqa: A002 - matches the query parameter name
    return service.chart(range)


@app.post("/api/review", dependencies=guard)
def review(idea: Idea):
    return service.review(idea.model_dump())


@app.post("/api/orders", dependencies=guard)
def place(req: PlaceRequest):
    return service.place(req.idea.model_dump(), req.acknowledged, req.confidence, req.feeling)


@app.delete("/api/orders/{order_id}", dependencies=guard)
def cancel(order_id: int):
    return service.cancel(order_id)


@app.get("/api/journal", dependencies=guard)
def journal():
    return service.journal_list()


@app.post("/api/journal/{entry_id}/review", dependencies=guard)
def journal_review(entry_id: int, note: ReviewNote):
    service.journal_review(entry_id, note.text)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

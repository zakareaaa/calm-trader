# Calm Trader (Binance Demo)

A simple trading dashboard that runs on your own laptop. It places real orders on
**Binance Demo Trading** (virtual money), and it shows only what matters:

- **A clean chart** with your buys and sells, your break-even line, and your open take-profit / stop-loss orders.
- **My position**: BTC held, average price, break-even after fees, and what you'd get if you sold now.
- **A simple order ticket**: buy now or at a price; sell now, at a price, or with an exit plan (take-profit + stop-loss together).
  Type "profit I want" or "max loss" in USDT and it works out the prices for you.
- **A review step before every order**: it blocks orders that can't work (for example a take-profit below break-even)
  and makes you tick a box before risky ones (no stop-loss, oversized trade, chasing a pump, bad reward to risk).
- **What's happening**: plain-language market notes (big moves, trend vs. moving averages, volume, streaks).
- **Mentor**: lessons in the spirit of Warren Buffett teaching an intern, plus a pre-trade checklist.
- **Journal**: every order is saved with your reason and how you felt, so you can review it later.

## Safety

- **Demo only.** The client refuses to talk to any host except `demo-api.binance.com`.
- **Your secret key never reaches the browser.** It stays in `.env` on your laptop; the Python backend signs requests.
- **The server only listens on your own computer** (`127.0.0.1`), and every API call needs a header that only this page sends.
- `.env` and `journal.db` are in `.gitignore` and `.dockerignore`, so they are never committed or baked into the Docker image.

## Setup (macOS)

### 1. Create a demo API key
1. Log in at **demo.binance.com**.
2. Open **https://demo.binance.com/en/my/settings/api-management** and create a key ("System generated").
3. Make sure **Spot trading** is enabled for the key. Copy the **API Key** and **Secret Key** (the secret is shown only once).

### 2. Install
```bash
cd calm-trader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
Open `.env` and paste your key and secret.

### 3. Run
```bash
source .venv/bin/activate        # if not already active
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open **http://127.0.0.1:8000** in Chrome. Stop the server with `Ctrl+C`.

### Alternative: run with Docker

If you have Docker Desktop installed you can skip the Python setup:

```bash
cp .env.example .env            # then paste your demo key and secret into .env
docker compose up --build -d    # build the image and start it in the background
```
Open **http://127.0.0.1:8000**. The port is published only on your own computer.
Your journal is kept in a Docker volume (`journal-data`), so it survives restarts and rebuilds.

```bash
docker compose logs -f          # watch the server output
docker compose down             # stop (add -v to also delete the journal volume)
docker compose run --rm app pytest -q   # run the offline tests inside the container
```
After changing `.env`, run `docker compose up -d` again so the container picks it up.

### 4. Run the tests (optional)
```bash
pytest -q
```
The tests use a fake Binance, so they run offline.

## How it's organised

```
app/
  binance_client.py  Signs and sends requests to Binance (demo only)
  portfolio.py       Average cost, break-even and realized P&L from your trade history
  checks.py          The pre-trade review rules (edit the limits at the top of the file)
  insights.py        Plain-language market highlights
  mentor.py          Lessons and the pre-trade checklist
  journal.py         SQLite journal (journal.db)
  service.py         Glues it all together; the web layer only calls this
  main.py            FastAPI routes
Dockerfile, docker-compose.yml   Optional containerised setup (see above)
static/              The dashboard (HTML, CSS, JS, no build step)
tests/               Offline tests with a fake Binance
```

API docs for your own experiments: **http://127.0.0.1:8000/docs** (send the header `X-Calm-Trader: 1`).

## Changing the rules

At the top of `app/checks.py`:

| Setting | Default | Meaning |
|---|---|---|
| `MAX_RISK_PCT` | 2.0 | Warn if a stop-loss would lose more than this % of your account |
| `MAX_SIZE_PCT` | 25.0 | Warn if one buy is more than this % of your account |
| `OVERTRADING` | 5 | Warn after this many trades in a day |

## Troubleshooting

| Message | Fix |
|---|---|
| "API key/secret missing" | Fill in `.env`, then restart the server |
| Docker: nothing on http://127.0.0.1:8000 | `docker compose ps` should show the container `healthy`; `docker compose logs` shows why if not |
| "Timestamp for this request is outside of the recvWindow" | Your Mac's clock is off. Turn on "Set time automatically" and restart |
| "Signature for this request is not valid" | The secret in `.env` is wrong or has extra spaces |
| "Invalid API-key, IP, or permissions" | Spot trading isn't enabled on the key, or it's a live key instead of a demo key |
| "Your BTC is locked in open sell orders" | Cancel the existing exit plan first, then place the new one |

## Notes

- Demo prices are realistic but not identical to the live market. A strategy that works here isn't proven to work with real money.
- Nothing here predicts prices. The highlights describe what has happened; the checks ask whether your plan makes sense.

"""The mentor: lessons in the spirit of Warren Buffett teaching an intern.

An honest note first: Buffett is a long-term business investor who has been
openly skeptical of Bitcoin and of short-term trading. So the mentor doesn't
pretend he'd approve of day trading. It applies his principles (protect your
capital, know what you own, stay patient, control your temperament) to what
you're actually doing.
"""
from __future__ import annotations

import datetime as dt

LESSONS = [
    ("Protect the capital first",
     "Buffett's first rule is \"Never lose money.\" He doesn't mean never have a losing trade. He means "
     "never take a loss so big it takes you out of the game. Size every trade so that being wrong is boring."),
    ("Margin of safety",
     "Buffett only buys when there's room for error between the price and what something is worth. "
     "For you that means a stop-loss and a position small enough that a 10% drop doesn't hurt."),
    ("Circle of competence",
     "Only trade what you understand. If you can't explain why BTC should go up from here in one sentence, "
     "you're guessing. Guessing is fine in demo, expensive with real money."),
    ("Temperament beats intelligence",
     "The biggest losses come from fear and greed, not from bad math. Notice when you want to trade because "
     "a candle is big and green or red. That feeling is the signal to wait."),
    ("Patience is a position",
     "Doing nothing is a decision, and often the best one. A good setup a week from now beats a mediocre one today."),
    ("Keep score honestly",
     "Write down every trade and why, then read it back. Most people remember their wins and forget their "
     "losses. Your journal won't."),
    ("Costs compound",
     "Fees look tiny: 0.2% a round trip. Trade 10 times a week and that's about 2% a week gone before "
     "you're right about anything. Fewer, better trades win."),
    ("Time horizon",
     "Decide before you buy whether this is a trade (days) or an investment (years), and act consistently. "
     "A trade that goes wrong shouldn't quietly become an 'investment'."),
]

CHECKLIST = [
    ("Trend", "Which way is the daily chart going? Are you trading with it or against it?"),
    ("Levels", "Where are the recent highs and lows? Those are where price often stalls or reverses."),
    ("Volume", "Is the move backed by heavy trading, or is it thin and easily reversed?"),
    ("News", "Any big event today (US inflation data, Fed decisions, exchange news)? Volatility spikes around them."),
    ("Exit if wrong", "Where's your stop-loss, and can you accept that loss calmly?"),
    ("Exit if right", "Where's your take-profit, and is it well above break-even after fees?"),
    ("Size", "If the stop hits, do you lose 1-2% of your account or less?"),
    ("Reason", "Is this a plan you wrote down, or a feeling from the last few candles?"),
    ("Horizon", "Is this a trade or an investment? Decide now, not after it moves against you."),
]


def mentor_notes(*, has_position: bool, has_exit_order: bool, recent_sells: list[dict],
                 trades_today: int, highlights: list[dict], position_pct: float) -> list[dict]:
    notes: list[dict] = []
    if has_position and not has_exit_order:
        notes.append({"level": "alert", "title": "Your BTC has no exit plan",
                      "detail": "You hold BTC with no take-profit or stop-loss order. If the price drops overnight, "
                                "nothing protects you. Set an exit plan (OCO) so the decision is made while you're calm."})
    last = recent_sells[-3:]
    if len(last) >= 2 and all(s["pnl"] < 0 for s in last):
        notes.append({"level": "watch", "title": f"{len(last)} losing sells in a row",
                      "detail": "Step away for today. Read your journal entries for these trades and look for the "
                                "common mistake before placing another order. Revenge trading is how small losses become big ones."})
    if trades_today >= 5:
        notes.append({"level": "watch", "title": "Busy day",
                      "detail": "Buffett: \"The stock market is a device for transferring money from the impatient to the patient.\" "
                                "Crypto works the same way. Fewer, better trades."})
    if any(h["level"] == "alert" and "range" in h.get("detail", "") for h in highlights):
        notes.append({"level": "watch", "title": "Big swings today",
                      "detail": "Buffett: \"Be fearful when others are greedy, and greedy when others are fearful.\" "
                                "Big days make everyone emotional. Your edge is staying calm and sticking to your plan."})
    if position_pct > 50:
        notes.append({"level": "watch", "title": f"{position_pct:.0f}% of your account is in BTC",
                      "detail": "That's a lot riding on one coin. Ask yourself: if BTC fell 30% next month, would I be okay?"})
    day = dt.date.today().toordinal()
    title, detail = LESSONS[day % len(LESSONS)]
    notes.append({"level": "info", "title": f"Today's lesson: {title}", "detail": detail})
    return notes

# stockmarkethelper

LLM-driven intraday trading agents for US equities (long-only), with a SwiftUI macOS monitor.

## Architecture

Two processes:

- **`engine/`** — headless Python daemon. Alpaca market data + paper orders, momentum/sentiment
  signals, regime filter, composite scoring, a local Ollama decision agent, a non-negotiable
  risk layer, a post-close daily summary, and a FastAPI IPC server.
- **`app/`** — SwiftUI macOS app connecting to the engine over localhost (read-only monitor).

The engine keeps trading even when the app is closed; a UI crash can never trigger or stop a trade.

## Run

1. `cd engine && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
2. `cp .env.example .env` and fill `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`.
3. Start Ollama locally (`ollama run llama3.2`).
4. `cd engine && .venv/bin/python -m autotrader.main --once` (single test scan, ignores market hours).
5. `cd engine && .venv/bin/python -m autotrader.main` (live: trades 9:30–16:00 ET, writes the daily summary once after close).
6. `cd app/TradingAgentApp && swift build` (or open in Xcode to run) for the macOS monitor.

## Market hours

The engine only scans and trades during regular US session hours (Mon–Fri, 9:30 AM–4:00 PM
Eastern). It sleeps otherwise and generates the daily summary **once**, after the close,
covering the whole day. No summary is produced until then. Holidays are not detected in v1
— run it only on regular trading days, or start/stop it via a daily scheduler.

## Risk (non-negotiable)

- 2% of equity per trade, max 3 concurrent positions.
- −10% from peak equity: hard kill-switch (flatten all + freeze until manually re-armed).
- −5% from day-start equity: stop trading for the day.

Paper trading only for the first 2 weeks; moving to real money is a manual, gated decision.

## Tests

```bash
cd engine && .venv/bin/pytest -q
```

## Known limitations (v1)

- The macOS app polls the engine over REST; WebSocket streaming is not yet wired.
- macOS notification banners for kill-switch / daily-stop are not yet implemented (the
  dashboard shows those states visually).
- `min_price` is loaded from config but the universe builder currently filters on volume
  only (Alpaca's most-active screener does not return price).


## Repo layout

- `engine/src/autotrader/` — engine package (`providers/`, `signals/`, `agent.py`, `risk.py`,
  `execution.py`, `runner.py`, `summary.py`, `ipc.py`, `config.py`, `state.py`, `models.py`, `main.py`)
- `engine/tests/` — pytest suite (TDD)
- `app/TradingAgentApp/` — SwiftUI app
- `docs/superpowers/specs/` — design spec
- `docs/superpowers/plans/` — implementation plan

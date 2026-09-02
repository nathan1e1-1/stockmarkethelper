import argparse
import threading
import time
from datetime import datetime, timezone

import uvicorn

from autotrader.agent import OllamaAgent
from autotrader.config import load_config
from autotrader.execution import AlpacaExecutor
from autotrader.history import HistoryRange
from autotrader.ipc import SharedState, create_app
from autotrader.lifecycle import EngineLifecycle
from autotrader.market import EASTERN, is_after_close, is_market_open
from autotrader.models import Equity
from autotrader.pnl import build_pnl_snapshot, enrich_pnl_snapshot
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.risk import RiskManager
from autotrader.runner import Runner
from autotrader.state import State, StateStore, same_day
from autotrader.summary import daily_summary
from autotrader.universe import build_universe


def _pnl_tickers(snapshot: dict) -> list[str]:
    tickers = [record["ticker"] for record in snapshot.get("open_positions", [])]
    tickers.extend(record["ticker"] for record in snapshot.get("realized_trades", []))
    return list(dict.fromkeys(ticker for ticker in tickers if isinstance(ticker, str) and ticker))


def _pnl_context(
    provider,
    bar_tickers: list[str],
    news_tickers: list[str],
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    bars_by_ticker, news_by_ticker = {}, {}
    for ticker in bar_tickers:
        try:
            bars_by_ticker[ticker] = provider.bars(ticker, history_range=HistoryRange.ONE_DAY)
        except Exception:
            bars_by_ticker[ticker] = []
    for ticker in news_tickers:
        try:
            news_by_ticker[ticker] = provider.news(ticker, limit=2)
        except Exception:
            news_by_ticker[ticker] = []
    return bars_by_ticker, news_by_ticker


def publish_pnl_attribution(shared, provider, equity, positions, closed_trades) -> None:
    prices = {}
    for position in positions:
        try:
            prices[position.ticker] = provider.latest_price(position.ticker)
        except Exception as error:
            print(f"[warn] latest price unavailable for {position.ticker}: {error}")
            prices[position.ticker] = None
    snapshot = build_pnl_snapshot(equity, positions, prices, closed_trades)
    open_tickers = list(dict.fromkeys(record["ticker"] for record in snapshot.get("open_positions", [])))
    bars_by_ticker, news_by_ticker = _pnl_context(provider, open_tickers, _pnl_tickers(snapshot))
    shared.pnl_attribution = enrich_pnl_snapshot(snapshot, bars_by_ticker, news_by_ticker)


def restore_same_day_state(loaded: State, day: str, runner, risk) -> bool:
    if not same_day(loaded, day):
        return False
    runner.decisions = loaded.decisions
    runner.closed_trades = loaded.closed_trades
    risk.day_start_equity = loaded.equity.day_start_equity
    risk.peak_equity = max(loaded.equity.peak_equity, risk.peak_equity)
    return True


def _parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    parser.add_argument(
        "--rearm",
        action="store_true",
        help="Locally re-arm a fully reconciled paper engine for the current session, then exit",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()

    cfg = load_config(args.config)
    provider = AlpacaProvider(cfg)
    agent = OllamaAgent(cfg.ollama_base_url, cfg.ollama_model)
    executor = AlpacaExecutor(cfg)
    risk = RiskManager(cfg)
    store = StateStore("state")
    shared = SharedState()

    runner = Runner(
        provider=provider,
        agent=agent,
        executor=executor,
        risk=risk,
        cfg=cfg,
        sentiment_llm=agent,
        state_store=store,
        clock=lambda: datetime.now(timezone.utc),
    )
    lifecycle = EngineLifecycle(
        cfg, executor, risk, runner, store, clock=lambda: datetime.now(timezone.utc)
    )

    app = create_app(shared, provider=provider, llm=agent)
    if not args.once:
        threading.Thread(
            target=uvicorn.run,
            kwargs={"app": app, "host": "127.0.0.1", "port": 8001, "log_level": "warning"},
            daemon=True,
        ).start()

    universe = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
    print(f"Universe: {universe}")

    startup_day = datetime.now(EASTERN).strftime("%Y-%m-%d")
    current_day = None
    reconciled = lifecycle.startup_reconcile()
    if not reconciled:
        print("[safety] startup reconciliation is incomplete; scanning is blocked")
    if args.rearm:
        if lifecycle.request_rearm(startup_day):
            print("[safety] paper engine re-armed after clean local reconciliation")
        else:
            print("[safety] paper engine was not re-armed; it requires a new session and clean broker reconciliation")
        return

    # Publish initial state so the UI shows account data immediately, even outside market hours.
    initial_equity = runner.equity.equity if runner.equity is not None else cfg.paper_capital
    runner.equity = runner.equity or Equity(
        equity=initial_equity,
        day_start_equity=risk.day_start_equity,
        peak_equity=risk.peak_equity,
        day=startup_day,
    )
    shared.equity = runner.equity
    shared.positions = list(risk.positions)
    shared.risk = risk
    publish_pnl_attribution(shared, provider, runner.equity, shared.positions, runner.closed_trades)

    def sync_and_scan(day: str) -> None:
        lifecycle.tick(datetime.now(timezone.utc), universe)
        equity = runner.equity.equity if runner.equity is not None else initial_equity
        shared.equity = runner.equity
        shared.positions = list(risk.positions)
        publish_pnl_attribution(shared, provider, runner.equity, shared.positions, runner.closed_trades)
        shared.decisions = runner.decisions
        shared.risk = risk
        shared.equity_history.append({"t": time.time(), "equity": equity})

    def generate_summary() -> None:
        unrealized = 0.0
        for p in risk.positions:
            unrealized += (provider.latest_price(p.ticker) - p.avg_entry_price) * p.qty
        state = State(
            equity=runner.equity,
            positions=risk.positions,
            decisions=runner.decisions,
            closed_trades=runner.closed_trades,
            unrealized_pnl=unrealized,
        )
        summary = daily_summary(state, agent)
        shared.summary = summary
        print(f"Daily summary:\n{summary}")

    if args.once:
        sync_and_scan(datetime.now(EASTERN).strftime("%Y-%m-%d"))
        generate_summary()
        return

    summary_done = False

    while True:
        now = datetime.now(EASTERN)
        day = now.strftime("%Y-%m-%d")

        try:
            if day != current_day:
                current_day = day
                summary_done = False
                shared.equity_history = []
                universe[:] = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
                print(f"Universe: {universe}")

            if is_market_open(now):
                sync_and_scan(day)
            elif is_after_close(now) and not summary_done:
                generate_summary()
                summary_done = True
        except Exception as e:
            print(f"[error] main loop: {e}")

        time.sleep(cfg.scan_interval_seconds)


if __name__ == "__main__":
    main()

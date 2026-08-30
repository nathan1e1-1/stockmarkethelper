import argparse
import threading
import time
from datetime import datetime

import uvicorn

from autotrader.agent import OllamaAgent
from autotrader.config import load_config
from autotrader.execution import AlpacaExecutor
from autotrader.ipc import SharedState, create_app
from autotrader.market import EASTERN, is_after_close, is_market_open
from autotrader.models import Equity
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.risk import RiskManager
from autotrader.runner import Runner
from autotrader.state import State, StateStore, same_day
from autotrader.summary import daily_summary
from autotrader.universe import build_universe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = AlpacaProvider(cfg)
    agent = OllamaAgent(cfg.ollama_base_url, cfg.ollama_model)
    executor = AlpacaExecutor(cfg)
    risk = RiskManager(cfg)
    store = StateStore("state")
    shared = SharedState()

    runner = Runner(provider=provider, agent=agent, executor=executor, risk=risk, cfg=cfg, sentiment_llm=agent)

    app = create_app(shared, provider=provider)
    if not args.once:
        threading.Thread(
            target=uvicorn.run,
            kwargs={"app": app, "host": "127.0.0.1", "port": 8001, "log_level": "warning"},
            daemon=True,
        ).start()

    universe = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
    print(f"Universe: {universe}")

    equity = executor.get_equity()
    risk.day_start_equity = equity
    risk.peak_equity = equity

    flatten_time = datetime.strptime(cfg.flatten_time, "%H:%M").time() if cfg.flatten_at_close else None
    reconciled = False

    def sync_and_scan(day: str) -> None:
        nonlocal reconciled
        if not args.once and not reconciled:
            runner.reconcile()
            reconciled = True
        equity = executor.get_equity()
        risk.peak_equity = max(risk.peak_equity, equity)
        risk.positions = executor.positions()
        runner.equity = Equity(
            equity=equity,
            day_start_equity=risk.day_start_equity,
            peak_equity=risk.peak_equity,
            day=day,
        )
        runner.manage_exits(flatten_time=flatten_time, now=datetime.now(EASTERN))
        runner.run_once(universe)
        shared.equity = runner.equity
        shared.positions = executor.positions()
        shared.decisions = runner.decisions
        shared.risk = risk
        shared.equity_history.append({"t": time.time(), "equity": equity})
        store.save(State(equity=runner.equity, positions=risk.positions, decisions=runner.decisions, closed_trades=runner.closed_trades))

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

    current_day = None
    summary_done = False

    startup_day = datetime.now(EASTERN).strftime("%Y-%m-%d")
    loaded = store.load()
    if same_day(loaded, startup_day):
        runner.decisions = loaded.decisions
        runner.closed_trades = loaded.closed_trades
        risk.day_start_equity = loaded.equity.day_start_equity
        risk.peak_equity = max(loaded.equity.peak_equity, risk.peak_equity)
        current_day = startup_day
        print(f"[reload] restored {len(runner.decisions)} decisions, {len(runner.closed_trades)} closed trades")

    while True:
        now = datetime.now(EASTERN)
        day = now.strftime("%Y-%m-%d")

        try:
            if day != current_day:
                current_day = day
                summary_done = False
                reconciled = False
                runner.decisions = []
                runner.closed_trades = []
                runner.flattened = False
                shared.equity_history = []
                universe[:] = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
                print(f"Universe: {universe}")
                equity = executor.get_equity()
                risk.day_start_equity = equity
                risk.peak_equity = max(risk.peak_equity, equity)

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

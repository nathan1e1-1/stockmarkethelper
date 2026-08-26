import argparse
import threading
import time

import uvicorn

from autotrader.agent import OllamaAgent
from autotrader.config import load_config
from autotrader.execution import AlpacaExecutor
from autotrader.ipc import SharedState, create_app
from autotrader.models import Equity
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.risk import RiskManager
from autotrader.runner import Runner
from autotrader.state import State, StateStore
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

    app = create_app(shared)
    if not args.once:
        threading.Thread(
            target=uvicorn.run,
            kwargs={"app": app, "host": "127.0.0.1", "port": 8000, "log_level": "warning"},
            daemon=True,
        ).start()

    universe = build_universe(provider, size=cfg.universe_size, min_volume=cfg.min_volume, tickers_only=True)
    print(f"Universe: {universe}")

    day = time.strftime("%Y-%m-%d")
    equity = executor.get_equity()
    risk.day_start_equity = equity
    risk.peak_equity = equity

    try:
        while True:
            equity = executor.get_equity()
            risk.peak_equity = max(risk.peak_equity, equity)
            risk.positions = executor.positions()
            runner.equity = Equity(
                equity=equity,
                day_start_equity=risk.day_start_equity,
                peak_equity=risk.peak_equity,
                day=day,
            )

            runner.run_once(universe)

            shared.equity = runner.equity
            shared.positions = executor.positions()
            shared.decisions = runner.decisions
            shared.risk = risk
            store.save(State(equity=runner.equity, positions=risk.positions, decisions=runner.decisions))

            if args.once:
                break
            time.sleep(cfg.scan_interval_seconds)
    finally:
        summary = daily_summary(State(equity=runner.equity, positions=risk.positions, decisions=runner.decisions), agent)
        shared.summary = summary
        print(f"Daily summary:\n{summary}")


if __name__ == "__main__":
    main()

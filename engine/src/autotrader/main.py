import argparse
import time

from autotrader.agent import OllamaAgent
from autotrader.config import load_config
from autotrader.execution import AlpacaExecutor
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.risk import RiskManager
from autotrader.runner import Runner
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

    runner = Runner(provider=provider, agent=agent, executor=executor, risk=risk, cfg=cfg, sentiment_llm=agent)

    universe = build_universe(provider, size=cfg.universe_size, min_volume=cfg.min_volume, tickers_only=True)
    print(f"Universe: {universe}")

    while True:
        runner.run_once(universe)
        if args.once:
            break
        time.sleep(cfg.scan_interval_seconds)


if __name__ == "__main__":
    main()

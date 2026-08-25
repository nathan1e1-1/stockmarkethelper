import json

from autotrader.models import AgentDecision, Decision, SignalSet


def parse_decision(raw: str) -> Decision:
    try:
        obj = json.loads(raw)
        return Decision(obj.get("decision", "hold"))
    except (json.JSONDecodeError, ValueError):
        return Decision.HOLD


class OllamaAgent:
    def __init__(self, base_url: str, model: str, session=None):
        import requests
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.session = session or requests.Session()

    def decide(self, signals: SignalSet) -> AgentDecision:
        try:
            prompt = (
                f"You are a disciplined intraday trader. Given these signals for {signals.ticker}: "
                f"regime={signals.regime}, composite={signals.composite}, "
                f"signals=" + json.dumps([{"name": s.name, "value": s.value} for s in signals.signals]) + ". "
                "Respond ONLY with JSON: {\"decision\": \"buy\"|\"hold\"|\"sell\", \"confidence\": 0.0-1.0, \"rationale\": \"...\"}"
            )
            resp = self.session.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "{}")
            obj = json.loads(text)
            return AgentDecision(
                ticker=signals.ticker,
                decision=Decision(obj.get("decision", "hold")),
                rationale=obj.get("rationale", ""),
                confidence=float(obj.get("confidence", 0.0)),
                signals=signals,
            )
        except Exception:
            return AgentDecision(
                ticker=signals.ticker,
                decision=Decision.HOLD,
                rationale="decision agent unavailable",
                confidence=0.0,
                signals=signals,
            )

    def complete(self, prompt: str) -> str:
        try:
            resp = self.session.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception:
            return "Daily summary unavailable."

    def sentiment(self, headlines: list[str]) -> float:
        try:
            prompt = (
                "Score the sentiment of these headlines from -1 (very negative) to 1 (very positive) "
                "for the stock. " + " | ".join(headlines) + " "
                'Respond ONLY with JSON: {"sentiment": <float>}'
            )
            resp = self.session.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=60,
            )
            resp.raise_for_status()
            obj = json.loads(resp.json().get("response", "{}"))
            return max(-1.0, min(1.0, float(obj.get("sentiment", 0.0))))
        except Exception:
            return 0.0

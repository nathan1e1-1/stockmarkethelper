from autotrader.state import State


def daily_summary(state: State, llm) -> str:
    eq = state.equity
    pnl = (eq.equity / eq.day_start_equity - 1.0) * 100 if eq and eq.day_start_equity else 0.0

    lines = []
    for d in state.decisions:
        signals = ""
        if d.signals:
            signals = ", ".join(f"{s.name}={s.value}" for s in d.signals.signals)
        parts = [f"{d.ticker}: {d.decision.value} (confidence {d.confidence:.2f})"]
        if d.rationale:
            parts.append(f"rationale: {d.rationale}")
        if signals:
            parts.append(f"signals: {signals}")
        lines.append("- " + " | ".join(parts))

    if lines:
        decision_block = "\n".join(lines)
    else:
        decision_block = "No trades were placed today."

    prompt = (
        "Write a concise, honest post-market summary for an intraday trading day. "
        f"Day P&L was {pnl:.2f}%. "
        f"Decisions:\n{decision_block}\n"
        "Cover: what went well, what went wrong, and one concrete improvement for tomorrow. "
        "Only reference the decisions listed above. Do not invent trades or tickers that are not listed."
    )
    return llm.complete(prompt)

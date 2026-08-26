from autotrader.state import State


def daily_summary(state: State, llm) -> str:
    eq = state.equity
    pnl = (eq.equity / eq.day_start_equity - 1.0) * 100 if eq and eq.day_start_equity else 0.0

    decision_lines = []
    for d in state.decisions:
        signals = ""
        if d.signals:
            signals = ", ".join(f"{s.name}={s.value}" for s in d.signals.signals)
        parts = [f"{d.ticker}: {d.decision.value} (confidence {d.confidence:.2f})"]
        if d.rationale:
            parts.append(f"rationale: {d.rationale}")
        if signals:
            parts.append(f"signals: {signals}")
        decision_lines.append("- " + " | ".join(parts))

    decision_block = "\n".join(decision_lines) if decision_lines else "No trades were placed today."

    if state.positions:
        position_block = "\n".join(
            f"- {p.ticker}: {p.qty:g} shares @ {p.avg_entry_price:.2f}"
            for p in state.positions
        )
    else:
        position_block = "No open positions."

    prompt = (
        "Write a concise, honest post-market summary for an intraday trading day.\n"
        f"Day P&L: {pnl:.2f}%\n"
        f"Decisions made:\n{decision_block}\n"
        f"Open positions at close:\n{position_block}\n"
        "Report only these facts. Do not claim that any individual trade won or lost; "
        "per-trade results are not available. If no trades were placed, say so plainly. "
        "Then suggest one concrete process improvement for tomorrow."
    )
    return llm.complete(prompt)

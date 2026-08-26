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

    if state.closed_trades:
        trade_lines = [
            f"- {t.ticker}: {t.exit_reason}, realized ${t.realized_pnl:+.2f}"
            for t in state.closed_trades
        ]
        total = sum(t.realized_pnl for t in state.closed_trades)
        trade_lines.append(f"Total realized P&L: ${total:+.2f}")
        trade_block = "\n".join(trade_lines)
    else:
        trade_block = "No trades were closed today."

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
        f"Closed trades:\n{trade_block}\n"
        f"Open positions at close:\n{position_block}\n"
        f"Unrealized P&L on open positions: ${getattr(state, 'unrealized_pnl', 0.0):+.2f}\n"
        "Report only the realized results listed above. Do not invent trades, tickers, or outcomes. "
        "Then suggest one concrete process improvement for tomorrow."
    )
    return llm.complete(prompt)

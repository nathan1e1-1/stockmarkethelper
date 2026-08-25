from autotrader.state import State


def daily_summary(state: State, llm) -> str:
    eq = state.equity
    pnl = (eq.equity / eq.day_start_equity - 1.0) * 100 if eq and eq.day_start_equity else 0.0
    prompt = (
        f"Write a concise post-market summary for an intraday trading day. "
        f"Day P&L was {pnl:.2f}%. {len(state.decisions)} decisions were made. "
        f"Cover: what went well, what went wrong, and one concrete improvement for tomorrow."
    )
    return llm.complete(prompt)

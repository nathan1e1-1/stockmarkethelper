import SwiftUI

struct PositionsView: View {
    @ObservedObject private var client = EngineClient.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                positionsSection.entrance()
                tradesSection.entrance(delay: 0.08)
                decisionsSection.entrance(delay: 0.16)
            }
            .padding(24)
            .frame(maxWidth: 920, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color.background)
        .task {
            client.start()
            await client.refresh()
        }
    }

    private var positionsSection: some View {
        let positions = client.status?.positions ?? []

        return VStack(alignment: .leading, spacing: 12) {
            SSectionLabel(text: "Open positions")

            if positions.isEmpty {
                emptyState("No open positions")
            } else {
                SCard {
                    VStack(spacing: 0) {
                        HStack {
                            Text("Ticker").frame(maxWidth: .infinity, alignment: .leading)
                            Text("Qty").frame(width: 90, alignment: .trailing)
                            Text("Entry").frame(width: 110, alignment: .trailing)
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.mutedForeground)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)

                        Divider().overlay(Color.border)

                        ForEach(positions, id: \.ticker) { p in
                            VStack(spacing: 0) {
                                HStack {
                                    Text(p.ticker)
                                        .font(.body.weight(.semibold))
                                        .foregroundStyle(Color.foreground)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    Text(p.qty, format: .number)
                                        .font(.body)
                                        .monospacedDigit()
                                        .foregroundStyle(Color.foreground)
                                        .frame(width: 90, alignment: .trailing)
                                    Text(p.avg_entry_price, format: .currency(code: "USD"))
                                        .font(.body)
                                        .monospacedDigit()
                                        .foregroundStyle(Color.foreground)
                                        .frame(width: 110, alignment: .trailing)
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 12)

                                if p.ticker != positions.last?.ticker {
                                    Divider().overlay(Color.border)
                                }
                            }
                        }
                    }
                    .padding(.vertical, 0)
                }
            }
        }
    }

    private var tradesSection: some View {
        let trades = client.status?.closed_trades ?? []

        return VStack(alignment: .leading, spacing: 12) {
            SSectionLabel(text: "Closed trades")

            if trades.isEmpty {
                emptyState("No trades closed yet")
            } else {
                SCard {
                    VStack(spacing: 0) {
                        HStack {
                            Text("Ticker").frame(maxWidth: .infinity, alignment: .leading)
                            Text("Qty").frame(width: 80, alignment: .trailing)
                            Text("Entry → Exit").frame(width: 170, alignment: .trailing)
                            Text("P&L").frame(width: 90, alignment: .trailing)
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.mutedForeground)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)

                        Divider().overlay(Color.border)

                        ForEach(trades) { t in
                            VStack(spacing: 0) {
                                HStack(alignment: .center, spacing: 12) {
                                    Text(t.ticker)
                                        .font(.body.weight(.semibold))
                                        .foregroundStyle(Color.foreground)
                                    exitReasonBadge(t.exit_reason)
                                    Spacer(minLength: 0)
                                    Text(t.realized_pnl, format: .currency(code: "USD").sign(strategy: .always()))
                                        .font(.body.weight(.semibold))
                                        .monospacedDigit()
                                        .foregroundStyle(t.realized_pnl >= 0 ? Color.gain : Color.loss)
                                        .frame(alignment: .trailing)
                                }
                                HStack {
                                    Text("\(t.qty, format: .number.precision(.fractionLength(0))) @ \(t.entry_price, format: .currency(code: "USD")) → \(t.exit_price, format: .currency(code: "USD"))")
                                        .font(.caption)
                                        .monospacedDigit()
                                        .foregroundStyle(Color.mutedForeground)
                                    Spacer()
                                    Text(shortTime(of: t.closed_at))
                                        .font(.caption2)
                                        .monospacedDigit()
                                        .foregroundStyle(Color.mutedForeground)
                                }
                                .padding(.top, 2)
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)

                            if t.id != trades.last?.id {
                                Divider().overlay(Color.border)
                            }
                        }
                    }
                    .padding(.vertical, 0)
                }
            }
        }
    }

    private func exitReasonBadge(_ reason: String) -> some View {
        switch reason.lowercased() {
        case "stop_loss": return SBadge(text: "STOP LOSS", variant: .destructive)
        case "take_profit": return SBadge(text: "TAKE PROFIT", variant: .success)
        case "flatten": return SBadge(text: "FLATTEN", variant: .secondary)
        default: return SBadge(text: reason.uppercased(), variant: .secondary)
        }
    }

    private func shortTime(of iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: iso) else { return iso }
        return date.formatted(.dateTime.hour(.twoDigits(amPM: .abbreviated)).minute())
    }

    private var decisionsSection: some View {
        let decisions = client.status?.decisions ?? []

        return VStack(alignment: .leading, spacing: 12) {
            SSectionLabel(text: "Decisions")

            if decisions.isEmpty {
                emptyState("No decisions yet")
            } else {
                SCard {
                    VStack(spacing: 0) {
                        ForEach(decisions, id: \.ticker) { d in
                            VStack(spacing: 0) {
                                HStack(alignment: .center, spacing: 12) {
                                    Text(d.ticker)
                                        .font(.body.weight(.semibold))
                                        .foregroundStyle(Color.foreground)
                                    decisionBadge(d.decision)
                                    Spacer()
                                    Text("confidence \(d.confidence, format: .number.precision(.fractionLength(2)))")
                                        .font(.caption)
                                        .monospacedDigit()
                                        .foregroundStyle(Color.mutedForeground)
                                }
                                if !d.rationale.isEmpty {
                                    Text(d.rationale)
                                        .font(.callout)
                                        .foregroundStyle(Color.mutedForeground)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding(.top, 4)
                                }
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)

                            if d.ticker != decisions.last?.ticker {
                                Divider().overlay(Color.border)
                            }
                        }
                    }
                    .padding(.vertical, 0)
                }
            }
        }
    }

    private func decisionBadge(_ decision: String) -> some View {
        switch decision.lowercased() {
        case "buy": return SBadge(text: "BUY", variant: .success)
        case "sell": return SBadge(text: "SELL", variant: .destructive)
        default: return SBadge(text: "HOLD", variant: .secondary)
        }
    }

    private func emptyState(_ message: String) -> some View {
        SCard {
            Text(message)
                .font(.callout)
                .foregroundStyle(Color.mutedForeground)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.vertical, 40)
        }
    }
}

import SwiftUI

struct PositionsView: View {
    @ObservedObject private var client = EngineClient.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                positionsSection
                decisionsSection
            }
            .padding(24)
            .frame(maxWidth: 920, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color.bg)
        .task {
            client.start()
            await client.refresh()
        }
    }

    private var positionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: "Open positions")

            let positions = client.status?.positions ?? []
            if positions.isEmpty {
                emptyState("No open positions")
            } else {
                VStack(spacing: 0) {
                    HStack {
                        Text("Ticker").frame(maxWidth: .infinity, alignment: .leading)
                        Text("Qty").frame(width: 90, alignment: .trailing)
                        Text("Entry").frame(width: 110, alignment: .trailing)
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundColor(.textSecondary)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)

                    Divider().overlay(Color.border)

                    ForEach(positions, id: \.ticker) { p in
                        VStack(spacing: 0) {
                            HStack {
                                Text(p.ticker).font(.body.weight(.semibold)).foregroundColor(.textPrimary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Text(p.qty, format: .number).font(.body).monospacedDigit().foregroundColor(.textPrimary)
                                    .frame(width: 90, alignment: .trailing)
                                Text(p.avg_entry_price, format: .currency(code: "USD")).font(.body).monospacedDigit().foregroundColor(.textPrimary)
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
                .card()
                .padding(0)
            }
        }
    }

    private var decisionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: "Decisions")

            let decisions = client.status?.decisions ?? []
            if decisions.isEmpty {
                emptyState("No decisions yet")
            } else {
                VStack(spacing: 0) {
                    ForEach(decisions, id: \.ticker) { d in
                        VStack(spacing: 0) {
                            HStack(alignment: .center, spacing: 12) {
                                Text(d.ticker).font(.body.weight(.semibold)).foregroundColor(.textPrimary)
                                decisionBadge(d.decision)
                                Spacer()
                                Text("confidence \(d.confidence, format: .number.precision(.fractionLength(2)))")
                                    .font(.caption)
                                    .monospacedDigit()
                                    .foregroundColor(.textSecondary)
                            }
                            if !d.rationale.isEmpty {
                                Text(d.rationale)
                                    .font(.callout)
                                    .foregroundColor(.textSecondary)
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
                .card()
                .padding(0)
            }
        }
    }

    private func decisionBadge(_ decision: String) -> some View {
        let (text, color): (String, Color) = {
            switch decision.lowercased() {
            case "buy": return ("BUY", .gain)
            case "sell": return ("SELL", .loss)
            default: return ("HOLD", .textSecondary)
            }
        }()
        return Text(text)
            .font(.caption.weight(.bold))
            .foregroundColor(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .clipShape(Capsule())
    }

    private func emptyState(_ message: String) -> some View {
        Text(message)
            .font(.callout)
            .foregroundColor(.textSecondary)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.vertical, 40)
            .card()
    }
}

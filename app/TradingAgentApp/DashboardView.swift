import SwiftUI

struct DashboardView: View {
    @ObservedObject private var client = EngineClient.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                statusLine

                if let eq = client.status?.equity {
                    equityHeader(eq)
                    stats(eq)
                } else {
                    waitingCard
                }

                alerts
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

    private var statusLine: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(client.connected ? Color.gain : Color.textSecondary)
                .frame(width: 8, height: 8)
            Text(client.connected ? "Engine connected" : "Engine offline")
                .font(.caption)
                .foregroundColor(.textSecondary)
            Spacer()
            Text("Live · 5s refresh")
                .font(.caption)
                .foregroundColor(.textSecondary)
        }
    }

    private func equityHeader(_ eq: Equity) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "Account equity")
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(eq.equity, format: .currency(code: "USD"))
                    .font(.system(size: 40, weight: .bold))
                    .monospacedDigit()
                    .foregroundColor(.textPrimary)
                pnlBadge(eq)
            }
        }
    }

    private func pnlBadge(_ eq: Equity) -> some View {
        let dayStart = eq.day_start_equity
        let pnl = dayStart > 0 ? (eq.equity / dayStart - 1) : 0
        let color = pnl >= 0 ? Color.gain : Color.loss
        return Text(pnl, format: .percent.precision(.fractionLength(2)))
            .font(.title3.weight(.semibold))
            .monospacedDigit()
            .foregroundColor(color)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(color.opacity(0.15))
            .clipShape(Capsule())
    }

    private func stats(_ eq: Equity) -> some View {
        let dayStart = eq.day_start_equity
        let pnl = dayStart > 0 ? (eq.equity / dayStart - 1) : 0
        let pnlColor = pnl >= 0 ? Color.gain : Color.loss

        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: "Today")
            HStack(spacing: 12) {
                StatCard(
                    title: "Day P&L",
                    value: (eq.equity - dayStart).formatted(.currency(code: "USD").sign(strategy: .always())),
                    tint: pnlColor
                )
                StatCard(
                    title: "Peak equity",
                    value: eq.peak_equity.formatted(.currency(code: "USD"))
                )
                StatCard(
                    title: "Day start",
                    value: dayStart.formatted(.currency(code: "USD"))
                )
                StatCard(
                    title: "Open positions",
                    value: "\(client.status?.positions.count ?? 0)"
                )
            }
        }
    }

    private var waitingCard: some View {
        VStack(spacing: 12) {
            Image(systemName: "antenna.radiowaves.left.and.right")
                .font(.system(size: 32))
                .foregroundColor(.textSecondary)
            Text("Waiting for engine…")
                .font(.title3.weight(.medium))
                .foregroundColor(.textPrimary)
            Text("Start the engine to see live account data.")
                .font(.callout)
                .foregroundColor(.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 60)
        .card()
    }

    @ViewBuilder
    private var alerts: some View {
        VStack(alignment: .leading, spacing: 12) {
            if client.status?.kill_switch == true {
                alertBanner(
                    icon: "exclamationmark.octagon.fill",
                    title: "Kill switch engaged",
                    detail: "Equity dropped 10% from peak. All trading halted.",
                    color: .loss
                )
            }
            if client.status?.daily_stop == true {
                alertBanner(
                    icon: "stop.circle.fill",
                    title: "Daily stop reached",
                    detail: "Trading halted for the rest of the day.",
                    color: .warn
                )
            }
        }
    }

    private func alertBanner(icon: String, title: String, detail: String, color: Color) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundColor(color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline).foregroundColor(color)
                Text(detail).font(.callout).foregroundColor(.textSecondary)
            }
            Spacer()
        }
        .padding(16)
        .background(color.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(color.opacity(0.5), lineWidth: 1))
    }
}

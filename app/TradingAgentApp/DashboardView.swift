import SwiftUI
import Charts

struct DashboardView: View {
    @ObservedObject private var client = EngineClient.shared
    @State private var highlightedEquityPoint: EquityPoint?

    var body: some View {
        ScrollView {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 24) {
                    dashboardContent
                        .frame(minWidth: 700, maxWidth: 920, alignment: .leading)
                    AITradeDeskView()
                        .frame(width: 340)
                }

                VStack(alignment: .leading, spacing: 24) {
                    dashboardContent
                    AITradeDeskView()
                        .frame(maxWidth: 540, alignment: .leading)
                }
            }
            .padding(24)
            .frame(maxWidth: 1_300, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color.background)
        .task {
            client.start()
            await client.refresh()
        }
    }

    private var dashboardContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            statusLine.entrance()

            if let eq = client.status?.equity {
                equityHeader(eq).entrance(delay: 0.05)
                stats(eq).entrance(delay: 0.1)
                pnlChart(eq).entrance(delay: 0.15)
            } else {
                waitingCard.entrance(delay: 0.05)
            }

            alerts.entrance(delay: 0.2)
        }
    }

    private var statusLine: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(client.connected ? Color.gain : Color.mutedForeground)
                .frame(width: 8, height: 8)
            Text(client.connected ? "Engine connected" : "Engine offline")
                .font(.caption)
                .foregroundStyle(Color.mutedForeground)
            Spacer()
            Text("Live · 5s refresh")
                .font(.caption)
                .foregroundStyle(Color.mutedForeground)
        }
    }

    private func equityHeader(_ eq: Equity) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            SSectionLabel(text: "Account equity")
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(eq.equity, format: .currency(code: "USD"))
                    .font(.system(size: 40, weight: .bold))
                    .monospacedDigit()
                    .foregroundStyle(Color.foreground)
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
            .foregroundStyle(color)
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
            SSectionLabel(text: "Today")
            HStack(spacing: 12) {
                SStatCard(
                    title: "Day P&L",
                    value: (eq.equity - dayStart).formatted(.currency(code: "USD").sign(strategy: .always())),
                    tint: pnlColor
                )
                SStatCard(title: "Peak equity", value: eq.peak_equity.formatted(.currency(code: "USD")))
                SStatCard(title: "Day start", value: dayStart.formatted(.currency(code: "USD")))
                SStatCard(title: "Open positions", value: "\(client.status?.positions.count ?? 0)")
            }
        }
    }

    private var waitingCard: some View {
        SCard {
            VStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(.system(size: 32))
                    .foregroundStyle(Color.mutedForeground)
                Text("Waiting for engine…")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(Color.foreground)
                Text("Start the engine to see live account data.")
                    .font(.callout)
                    .foregroundStyle(Color.mutedForeground)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 40)
        }
    }

    private func pnlChart(_ eq: Equity) -> some View {
        let history = client.status?.equity_history ?? []
        let dayStart = eq.day_start_equity

        return SCard {
            VStack(alignment: .leading, spacing: 12) {
                SCardHeader(title: "P&L today", subtitle: "Cumulative profit/loss vs day start")

                if history.count < 2 {
                    Text("Not enough data yet — history accumulates during market hours.")
                        .font(.callout)
                        .foregroundStyle(Color.mutedForeground)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, 24)
                } else {
                    let lastPnl = (history.last?.equity ?? dayStart) - dayStart
                    let color = lastPnl >= 0 ? Color.gain : Color.loss

                    Chart {
                        ForEach(history) { point in
                            pnlMarks(for: point, dayStart: dayStart, color: color)
                        }

                        RuleMark(y: .value("Zero", 0.0))
                            .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            .foregroundStyle(Color.border)

                        if let highlightedEquityPoint {
                            RuleMark(x: .value("Selected time", highlightedEquityPoint.date))
                                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                                .foregroundStyle(Color.mutedForeground)
                                .annotation(
                                    position: .top,
                                    overflowResolution: .init(x: .fit(to: .plot), y: .fit(to: .plot))
                                ) {
                                    pnlTooltip(for: highlightedEquityPoint, dayStart: dayStart)
                                }
                        }
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading) { _ in
                            AxisGridLine().foregroundStyle(Color.border)
                            AxisValueLabel(format: .currency(code: "USD").precision(.fractionLength(0)))
                                .foregroundStyle(Color.mutedForeground)
                        }
                    }
                    .chartXAxis {
                        AxisMarks { _ in
                            AxisGridLine().foregroundStyle(Color.border)
                            AxisValueLabel(format: .dateTime.hour(.twoDigits(amPM: .omitted)).minute())
                                .foregroundStyle(Color.mutedForeground)
                        }
                    }
                    .chartOverlay { proxy in
                        GeometryReader { geometry in
                            Rectangle()
                                .fill(.clear)
                                .contentShape(Rectangle())
                                .onContinuousHover { phase in
                                    switch phase {
                                    case .active(let location):
                                        guard let plotAreaFrame = proxy.plotFrame else {
                                            highlightedEquityPoint = nil
                                            return
                                        }
                                        let plotFrame = geometry[plotAreaFrame]
                                        guard plotFrame.contains(location),
                                              let date = proxy.value(atX: location.x - plotFrame.origin.x, as: Date.self) else {
                                            highlightedEquityPoint = nil
                                            return
                                        }
                                        highlightedEquityPoint = nearestEquityPoint(to: date, in: history)
                                    case .ended:
                                        highlightedEquityPoint = nil
                                    }
                                }
                        }
                    }
                    .frame(height: 220)
                }
            }
            .padding(20)
        }
        .onChange(of: history.flatMap { [$0.t, $0.equity] }) { _, _ in
            highlightedEquityPoint = nil
        }
    }

    private func pnlTooltip(for point: EquityPoint, dayStart: Double) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(point.date.formatted(.dateTime.month(.abbreviated).day().hour().minute()))
            Text("Equity \(point.equity.formatted(.currency(code: "USD")))")
            Text("P&L \((point.equity - dayStart).formatted(.currency(code: "USD").sign(strategy: .always())))")
        }
        .font(.caption2.monospacedDigit())
        .foregroundStyle(Color.foreground)
        .padding(8)
        .background(Color.background)
        .clipShape(RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous)
                .stroke(Color.border, lineWidth: 1)
        )
    }

    @ChartContentBuilder
    private func pnlMarks(for point: EquityPoint, dayStart: Double, color: Color) -> some ChartContent {
        let pnl = point.equity - dayStart
        AreaMark(
            x: .value("Time", point.date),
            yStart: .value("P&L", 0.0),
            yEnd: .value("P&L", pnl)
        )
        .interpolationMethod(.monotone)
        .foregroundStyle(
            LinearGradient(colors: [color.opacity(0.25), .clear], startPoint: .top, endPoint: .bottom)
        )

        LineMark(x: .value("Time", point.date), y: .value("P&L", pnl))
            .interpolationMethod(.monotone)
            .foregroundStyle(color)
    }

    @ViewBuilder
    private var alerts: some View {
        VStack(alignment: .leading, spacing: 12) {
            if client.status?.kill_switch == true {
                SAlert(
                    icon: "exclamationmark.octagon.fill",
                    title: "Kill switch engaged",
                    description: "Equity dropped 10% from peak. All trading halted.",
                    variant: .destructive
                )
            }
            if client.status?.daily_stop == true {
                SAlert(
                    icon: "stop.circle.fill",
                    title: "Daily stop reached",
                    description: "Trading halted for the rest of the day.",
                    variant: .warning
                )
            }
        }
    }
}

import SwiftUI
import Charts

struct ChartsView: View {
    @ObservedObject private var client = EngineClient.shared
    @State private var query = ""
    @State private var bars: [Bar] = []
    @State private var loading = false

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            SInput(text: $query, placeholder: "Search ticker…", systemImage: "magnifyingglass") {
                query = query.uppercased()
            }
            .frame(maxWidth: 480)
            .entrance()

            if query.isEmpty {
                emptyState.entrance(delay: 0.06)
            } else {
                chart.entrance(delay: 0.06)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.background)
        .task(id: query) { await load() }
    }

    private var emptyState: some View {
        SCard {
            VStack(spacing: 12) {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: 32))
                    .foregroundStyle(Color.mutedForeground)
                Text("Search a ticker")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(Color.foreground)
                Text("Type a symbol like AAPL or NVDA to view its candlestick chart.")
                    .font(.callout)
                    .foregroundStyle(Color.mutedForeground)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private var chart: some View {
        if loading && bars.isEmpty {
            SCard {
                VStack(spacing: 12) {
                    ProgressView().controlSize(.large)
                    Text("Loading bars…")
                        .font(.callout)
                        .foregroundStyle(Color.mutedForeground)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else if bars.isEmpty {
            SCard {
                VStack(spacing: 12) {
                    Image(systemName: "chart.bar.xaxis")
                        .font(.system(size: 28))
                        .foregroundStyle(Color.mutedForeground)
                    Text("No data for \(query)")
                        .font(.title3.weight(.medium))
                        .foregroundStyle(Color.foreground)
                    Text("The engine may be offline or the ticker returned no bars.")
                        .font(.callout)
                        .foregroundStyle(Color.mutedForeground)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else {
            candleChart
        }
    }

    private var candleChart: some View {
        let last = bars.last

        return SCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text(query).font(.title2.weight(.bold)).foregroundStyle(Color.foreground)
                    if let last {
                        let change = last.c - last.o
                        Text(last.c, format: .currency(code: "USD"))
                            .font(.title2.weight(.semibold))
                            .monospacedDigit()
                            .foregroundStyle(change >= 0 ? Color.gain : Color.loss)
                    }
                    Spacer()
                    SBadge(text: "1-min · live", variant: .outline)
                }

                Chart {
                    ForEach(bars) { bar in
                        RectangleMark(
                            x: .value("Time", bar.date),
                            yStart: .value("Open", bar.o),
                            yEnd: .value("Close", bar.c),
                            width: .fixed(6)
                        )
                        .foregroundStyle(bar.c >= bar.o ? Color.gain : Color.loss)

                        RuleMark(
                            x: .value("Time", bar.date),
                            yStart: .value("Low", bar.l),
                            yEnd: .value("High", bar.h)
                        )
                        .lineStyle(StrokeStyle(lineWidth: 1))
                        .foregroundStyle(bar.c >= bar.o ? Color.gain : Color.loss)
                    }
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .chartYAxis {
                    AxisMarks(position: .leading) { _ in
                        AxisGridLine().foregroundStyle(Color.border)
                        AxisValueLabel().foregroundStyle(Color.mutedForeground)
                    }
                }
                .chartXAxis {
                    AxisMarks { _ in
                        AxisGridLine().foregroundStyle(Color.border)
                        AxisValueLabel(format: .dateTime.hour(.twoDigits(amPM: .omitted)).minute())
                            .foregroundStyle(Color.mutedForeground)
                    }
                }
                .animation(.easeInOut(duration: 0.5), value: bars.count)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private func load() async {
        guard !query.isEmpty else { bars = []; return }
        loading = true
        bars = await client.bars(for: query)
        loading = false
    }
}

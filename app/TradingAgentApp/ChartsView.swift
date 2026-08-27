import SwiftUI
import Charts

struct ChartsView: View {
    @ObservedObject private var client = EngineClient.shared
    @State private var query = ""
    @State private var bars: [Bar] = []
    @State private var loading = false

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            searchField
            if query.isEmpty {
                emptyState
            } else {
                chart
            }
        }
        .padding(24)
        .frame(maxWidth: 920, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.bg)
        .task(id: query) { await load() }
    }

    private var searchField: some View {
        HStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .foregroundColor(.textSecondary)
            TextField("Search ticker…", text: $query)
                .textFieldStyle(.plain)
                .font(.body)
                .foregroundColor(.textPrimary)
                .onSubmit { query = query.uppercased() }
            if !query.isEmpty {
                Button { query = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.textSecondary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(Color.surface)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.border, lineWidth: 1))
        .frame(maxWidth: 480)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 32))
                .foregroundColor(.textSecondary)
            Text("Search a ticker")
                .font(.title3.weight(.medium))
                .foregroundColor(.textPrimary)
            Text("Type a symbol like AAPL or NVDA to view its candlestick chart.")
                .font(.callout)
                .foregroundColor(.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 60)
        .card()
    }

    @ViewBuilder
    private var chart: some View {
        if loading && bars.isEmpty {
            VStack(spacing: 12) {
                ProgressView().controlSize(.large)
                Text("Loading bars…").font(.callout).foregroundColor(.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 60)
            .card()
        } else if bars.isEmpty {
            VStack(spacing: 12) {
                Image(systemName: "chart.bar.xaxis")
                    .font(.system(size: 28))
                    .foregroundColor(.textSecondary)
                Text("No data for \(query)")
                    .font(.title3.weight(.medium))
                    .foregroundColor(.textPrimary)
                Text("The engine may be offline or the ticker returned no bars.")
                    .font(.callout)
                    .foregroundColor(.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 48)
            .card()
        } else {
            candleChart
        }
    }

    private var candleChart: some View {
        let last = bars.last

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(query).font(.title2.weight(.bold)).foregroundColor(.textPrimary)
                if let last {
                    let change = last.c - last.o
                    Text(last.c, format: .currency(code: "USD"))
                        .font(.title2.weight(.semibold))
                        .monospacedDigit()
                        .foregroundColor(change >= 0 ? .gain : .loss)
                }
                Spacer()
                Text("1-min bars · live")
                    .font(.caption)
                    .foregroundColor(.textSecondary)
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
                    AxisValueLabel().foregroundStyle(Color.textSecondary)
                }
            }
            .chartXAxis {
                AxisMarks { _ in
                    AxisGridLine().foregroundStyle(Color.border)
                    AxisValueLabel(format: .dateTime.hour(.twoDigits(amPM: .omitted)).minute())
                        .foregroundStyle(Color.textSecondary)
                }
            }
            .frame(height: 340)
        }
        .card()
    }

    private func load() async {
        guard !query.isEmpty else { bars = []; return }
        loading = true
        bars = await client.bars(for: query)
        loading = false
    }
}

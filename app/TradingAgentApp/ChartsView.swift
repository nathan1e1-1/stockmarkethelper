import SwiftUI
import Charts

private struct PricePoint: Identifiable {
    let id = UUID()
    let index: Int
    let price: Double
}

struct ChartsView: View {
    @State private var query = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
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
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 32))
                .foregroundColor(.textSecondary)
            Text("Search a ticker")
                .font(.title3.weight(.medium))
                .foregroundColor(.textPrimary)
            Text("Type a symbol like AAPL or NVDA to view its chart.")
                .font(.callout)
                .foregroundColor(.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 60)
        .card()
    }

    private var chart: some View {
        let points = sampleData(for: query)
        let minPrice = points.map(\.price).min() ?? 0
        let current = points.last?.price ?? 0

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(query).font(.title2.weight(.bold)).foregroundColor(.textPrimary)
                Text(current, format: .currency(code: "USD"))
                    .font(.title2.weight(.semibold))
                    .monospacedDigit()
                    .foregroundColor(.accent)
                Spacer()
                Text("Preview data")
                    .font(.caption)
                    .foregroundColor(.textSecondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.warn.opacity(0.15))
                    .foregroundColor(.warn)
                    .clipShape(Capsule())
            }

            Chart(points) { point in
                AreaMark(
                    x: .value("Time", point.index),
                    yStart: .value("Price", minPrice),
                    yEnd: .value("Price", point.price)
                )
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.accent.opacity(0.25), Color.accent.opacity(0.0)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .interpolationMethod(.catmullRom)

                LineMark(x: .value("Time", point.index), y: .value("Price", point.price))
                    .foregroundStyle(Color.accent)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                    .interpolationMethod(.catmullRom)
            }
            .chartYAxis {
                AxisMarks(position: .leading) { _ in
                    AxisGridLine().foregroundStyle(Color.border)
                    AxisValueLabel().foregroundStyle(Color.textSecondary)
                }
            }
            .chartXAxis {
                AxisMarks { _ in
                    AxisGridLine().foregroundStyle(Color.border)
                    AxisValueLabel().foregroundStyle(Color.textSecondary)
                }
            }
            .frame(height: 320)

            Text("Chart data is a preview. Live bars from the engine will replace this once the chart endpoint is wired.")
                .font(.caption)
                .foregroundColor(.textSecondary)
        }
        .card()
    }

    private func sampleData(for ticker: String) -> [PricePoint] {
        var seed = 100.0 + Double(ticker.unicodeScalars.reduce(0) { $0 + Int($1.value) } % 2000) / 10.0
        var rng = Double(ticker.unicodeScalars.reduce(0) { $0 + Int($1.value) })
        var points: [PricePoint] = []
        for i in 0..<80 {
            rng = (rng * 110.3515245 + 12345).truncatingRemainder(dividingBy: 98765)
            let drift = (rng / 98765.0 - 0.5) * 4.0
            seed = max(1.0, seed + drift)
            points.append(PricePoint(index: i, price: seed))
        }
        return points
    }
}

import SwiftUI
import Charts

struct ChartsView: View {
    @ObservedObject private var client = EngineClient.shared
    @State private var query = ""
    @State private var suggestions: [Asset] = []
    @State private var highlightedSuggestion: Int?
    @State private var suggestionsLoading = false
    @State private var selectedTicker: String?
    @State private var selectedName = ""
    @State private var selectedRange: ChartRange = .oneDay
    @State private var bars: [Bar] = []
    @State private var barsLoading = false
    @State private var visibleDomain: TimeInterval = 1
    @State private var scrollPosition = Date()
    @State private var highlightedBar: Bar?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            searchPanel.entrance()

            if let selectedTicker {
                rangePicker.entrance(delay: 0.04)
                chartContent(for: selectedTicker).entrance(delay: 0.08)
            } else {
                emptyState.entrance(delay: 0.06)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.background)
        .onKeyPress(.downArrow) {
            moveHighlight(by: 1)
            return suggestions.isEmpty ? .ignored : .handled
        }
        .onKeyPress(.upArrow) {
            moveHighlight(by: -1)
            return suggestions.isEmpty ? .ignored : .handled
        }
        .onKeyPress(.return) {
            selectHighlightedSuggestion()
            return highlightedSuggestion == nil ? .ignored : .handled
        }
        .onKeyPress(.escape) {
            let wasShowingSuggestions = !suggestions.isEmpty || suggestionsLoading
            dismissSuggestions()
            return wasShowingSuggestions ? .handled : .ignored
        }
        .task(id: query) { await searchAssets() }
        .task(id: "\(selectedTicker ?? "")-\(selectedRange.rawValue)") { await loadBars() }
    }

    private var searchPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Find an equity")
                .font(.callout.weight(.medium))
                .foregroundStyle(Color.foreground)

            SInput(text: $query, placeholder: "Symbol or company name", systemImage: "magnifyingglass") {
                selectHighlightedSuggestion()
            }
            .accessibilityLabel("Search stocks by symbol or company name")
            .frame(maxWidth: 480)

            searchResults
        }
        .frame(maxWidth: 480, alignment: .leading)
    }

    @ViewBuilder
    private var searchResults: some View {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedQuery.isEmpty {
            if suggestionsLoading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Searching active, tradable US equities…")
                }
                .font(.caption)
                .foregroundStyle(Color.mutedForeground)
                .accessibilityElement(children: .combine)
            } else if !suggestions.isEmpty {
                SCard {
                    VStack(spacing: 0) {
                        ForEach(Array(suggestions.enumerated()), id: \.element.id) { index, asset in
                            Button {
                                select(asset)
                            } label: {
                                HStack(spacing: 10) {
                                    Text(asset.ticker)
                                        .font(.callout.weight(.semibold))
                                        .monospaced()
                                        .foregroundStyle(Color.foreground)
                                        .frame(width: 64, alignment: .leading)
                                    Text(asset.name)
                                        .font(.callout)
                                        .foregroundStyle(Color.mutedForeground)
                                        .lineLimit(1)
                                    Spacer(minLength: 0)
                                }
                                .padding(.horizontal, 12)
                                .frame(minHeight: 40)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(highlightedSuggestion == index ? Color.secondary : Color.clear)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(asset.ticker), \(asset.name)")
                            .accessibilityHint("Select this equity")

                            if index < suggestions.count - 1 {
                                Divider().overlay(Color.border)
                            }
                        }
                    }
                }
                .accessibilityLabel("Search suggestions")
            } else if !client.connected {
                SAlert(icon: "wifi.exclamationmark", title: "Market search is unavailable", description: "Check that the local trading engine is running, then try again.", variant: .warning)
            } else {
                SAlert(icon: "magnifyingglass", title: "No matching equities", description: "Try a ticker or a different part of the company name.")
            }
        }
    }

    private var rangePicker: some View {
        HStack(spacing: 8) {
            Text("Range")
                .font(.callout.weight(.medium))
                .foregroundStyle(Color.foreground)
            ForEach(ChartRange.allCases) { range in
                Button(rangeDisplayName(range)) {
                    highlightedBar = nil
                    selectedRange = range
                }
                    .buttonStyle(.bordered)
                    .tint(selectedRange == range ? Color.primary : Color.secondary)
                    .accessibilityLabel("\(rangeDisplayName(range)) range")
                    .accessibilityValue(selectedRange == range ? "Selected" : "Not selected")
            }
            Spacer()
        }
        .controlSize(.small)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Chart range")
    }

    private var emptyState: some View {
        SCard {
            VStack(spacing: 12) {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: 32))
                    .foregroundStyle(Color.mutedForeground)
                Text("Search an equity")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(Color.foreground)
                Text("Choose a ticker to explore its historical candlesticks, price range, and OHLC data.")
                    .font(.callout)
                    .foregroundStyle(Color.mutedForeground)
                    .multilineTextAlignment(.center)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private func chartContent(for ticker: String) -> some View {
        if barsLoading && bars.isEmpty {
            loadingCard(message: "Loading \(rangeDisplayName(selectedRange)) history for \(ticker)…")
        } else if bars.isEmpty {
            unavailableBarsCard(for: ticker)
        } else {
            candleChart(for: ticker)
        }
    }

    private func loadingCard(message: String) -> some View {
        SCard {
            VStack(spacing: 12) {
                ProgressView().controlSize(.large)
                Text(message).font(.callout).foregroundStyle(Color.mutedForeground)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityElement(children: .combine)
        }
    }

    private func unavailableBarsCard(for ticker: String) -> some View {
        SCard {
            VStack(spacing: 12) {
                Image(systemName: client.connected ? "chart.bar.xaxis" : "wifi.exclamationmark")
                    .font(.system(size: 28))
                    .foregroundStyle(Color.mutedForeground)
                Text(client.connected ? "No bars for \(ticker)" : "Chart data is unavailable")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(Color.foreground)
                Text(client.connected ? "No \(rangeDisplayName(selectedRange)) historical bars were returned for this equity." : "Check that the local trading engine is running, then retry the request.")
                    .font(.callout)
                    .foregroundStyle(Color.mutedForeground)
                    .multilineTextAlignment(.center)
                Button("Retry") { Task { await loadBars() } }.buttonStyle(.bordered)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func candleChart(for ticker: String) -> some View {
        let last = bars.last
        let periodChange = (bars.last?.c ?? 0) - (bars.first?.o ?? 0)

        return SCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(ticker).font(.title2.weight(.bold)).foregroundStyle(Color.foreground)
                        if !selectedName.isEmpty {
                            Text(selectedName).font(.callout).foregroundStyle(Color.mutedForeground)
                        }
                    }
                    if let last {
                        VStack(alignment: .trailing, spacing: 3) {
                            Text(last.c, format: .currency(code: "USD"))
                                .font(.title2.weight(.semibold)).monospacedDigit()
                                .foregroundStyle(periodChange >= 0 ? Color.gain : Color.loss)
                            Text(formattedPeriodChange(periodChange))
                                .font(.caption.weight(.medium)).monospacedDigit()
                                .foregroundStyle(periodChange >= 0 ? Color.gain : Color.loss)
                        }
                    }
                    Spacer()
                    SBadge(text: "\(rangeDisplayName(selectedRange)) · \(barIntervalLabel)", variant: .outline)
                }

                HStack(spacing: 8) {
                    Text("Candles: filled = close at or above open; dashed wick = close below open.")
                        .font(.caption).foregroundStyle(Color.mutedForeground)
                    Spacer()
                    Button("Zoom out", systemImage: "minus.magnifyingglass") { zoom(by: 1.5) }
                        .accessibilityLabel("Zoom chart out")
                    Button("Zoom in", systemImage: "plus.magnifyingglass") { zoom(by: 1 / 1.5) }
                        .accessibilityLabel("Zoom chart in")
                    Button("Reset", systemImage: "arrow.counterclockwise") { resetChartView() }
                        .accessibilityLabel("Reset chart zoom and position")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Chart {
                    ForEach(bars) { bar in
                        candleMarks(for: bar)
                    }

                    if let highlightedBar {
                        RuleMark(x: .value("Selected time", highlightedBar.date))
                            .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            .foregroundStyle(Color.mutedForeground)
                            .annotation(position: .top) {
                                candleTooltip(for: highlightedBar)
                            }
                    }
                }
                .chartScrollableAxes(.horizontal)
                .chartXVisibleDomain(length: visibleDomain)
                .chartScrollPosition(x: $scrollPosition)
                .chartYScale(domain: .automatic(includesZero: false))
                .chartYAxis {
                    AxisMarks(position: .leading) { _ in
                        AxisGridLine().foregroundStyle(Color.border)
                        AxisValueLabel().foregroundStyle(Color.mutedForeground)
                    }
                }
                .chartXAxis {
                    AxisMarks { value in
                        AxisGridLine().foregroundStyle(Color.border)
                        AxisValueLabel {
                            if let date = value.as(Date.self) {
                                Text(axisLabel(for: date)).foregroundStyle(Color.mutedForeground)
                            }
                        }
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
                                        highlightedBar = nil
                                        return
                                    }
                                    let plotFrame = geometry[plotAreaFrame]
                                    guard plotFrame.contains(location),
                                          let date = proxy.value(atX: location.x - plotFrame.origin.x, as: Date.self) else {
                                        highlightedBar = nil
                                        return
                                    }
                                    highlightedBar = nearestBar(to: date, in: bars)
                                case .ended:
                                    highlightedBar = nil
                                }
                            }
                    }
                }
                .frame(minHeight: 280, maxHeight: .infinity)
                .accessibilityLabel(accessibilitySummary(for: ticker, periodChange: periodChange))
                .accessibilityHint("Use the zoom controls and horizontal scrolling to explore the selected range.")

                DisclosureGroup("OHLC data") {
                    Table(Array(bars.suffix(24))) {
                        TableColumn("Time") { bar in Text(ohlcDateLabel(for: bar.date)) }
                        TableColumn("Open") { bar in Text(bar.o, format: .currency(code: "USD")) }
                        TableColumn("High") { bar in Text(bar.h, format: .currency(code: "USD")) }
                        TableColumn("Low") { bar in Text(bar.l, format: .currency(code: "USD")) }
                        TableColumn("Close") { bar in Text(bar.c, format: .currency(code: "USD")) }
                    }
                    .frame(minHeight: 180, maxHeight: 260)
                    .accessibilityLabel("Latest 24 OHLC bars")
                }
                .font(.callout)
                .foregroundStyle(Color.foreground)
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var barIntervalLabel: String {
        switch selectedRange {
        case .oneDay: return "intraday"
        case .fiveDays: return "5-minute bars"
        case .oneMonth: return "hourly bars"
        case .sixMonths, .oneYear: return "daily bars"
        case .max: return "daily bars (thinned)"
        }
    }

    private func rangeDisplayName(_ range: ChartRange) -> String { range == .max ? "Max" : range.rawValue }

    private func axisLabel(for date: Date) -> String {
        switch selectedRange {
        case .oneDay: return date.formatted(.dateTime.hour().minute())
        case .fiveDays, .oneMonth: return date.formatted(.dateTime.month(.abbreviated).day())
        case .sixMonths, .oneYear, .max: return date.formatted(.dateTime.month(.abbreviated).year())
        }
    }

    private func ohlcDateLabel(for date: Date) -> String {
        switch selectedRange {
        case .oneDay: return date.formatted(.dateTime.month(.abbreviated).day().hour().minute())
        default: return date.formatted(.dateTime.year().month(.abbreviated).day())
        }
    }

    private func candleTooltip(for bar: Bar) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(ohlcDateLabel(for: bar.date))
            Text("O \(bar.o.formatted(.currency(code: "USD")))  H \(bar.h.formatted(.currency(code: "USD")))")
            Text("L \(bar.l.formatted(.currency(code: "USD")))  C \(bar.c.formatted(.currency(code: "USD")))")
            Text("Vol \(bar.v.formatted(.number.precision(.fractionLength(0))))")
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
    private func candleMarks(for bar: Bar) -> some ChartContent {
        let rising = bar.c >= bar.o
        let color = rising ? Color.gain : Color.loss
        RectangleMark(
            x: .value("Time", bar.date),
            yStart: .value("Open", bar.o),
            yEnd: .value("Close", bar.c),
            width: .ratio(0.7)
        )
        .foregroundStyle(color)

        RuleMark(x: .value("Time", bar.date), yStart: .value("Low", bar.l), yEnd: .value("High", bar.h))
            .lineStyle(StrokeStyle(lineWidth: 1.5, dash: rising ? [] : [3, 2]))
            .foregroundStyle(color)
    }

    private func accessibilitySummary(for ticker: String, periodChange: Double) -> String {
        let close = bars.last?.c ?? 0
        let direction = periodChange >= 0 ? "up" : "down"
        return "\(ticker), \(rangeDisplayName(selectedRange)) chart. Latest close \(close.formatted(.currency(code: "USD"))). Period change \(direction) \(abs(periodChange).formatted(.currency(code: "USD"))). \(bars.count) bars."
    }

    private func formattedPeriodChange(_ change: Double) -> String {
        let prefix = change >= 0 ? "+" : ""
        return "\(prefix)\(change.formatted(.currency(code: "USD")))"
    }

    private func moveHighlight(by offset: Int) {
        guard !suggestions.isEmpty else { return }
        let current = highlightedSuggestion ?? (offset > 0 ? -1 : 0)
        highlightedSuggestion = min(max(current + offset, 0), suggestions.count - 1)
    }

    private func selectHighlightedSuggestion() {
        guard let highlightedSuggestion, suggestions.indices.contains(highlightedSuggestion) else { return }
        select(suggestions[highlightedSuggestion])
    }

    private func select(_ asset: Asset) {
        highlightedBar = nil
        selectedTicker = asset.ticker
        selectedName = asset.name
        query = asset.ticker
        dismissSuggestions()
    }

    private func dismissSuggestions() {
        suggestions = []
        highlightedSuggestion = nil
        suggestionsLoading = false
    }

    private func searchAssets() async {
        let searchQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard searchQuery != selectedTicker else { return }
        guard !searchQuery.isEmpty else {
            dismissSuggestions()
            return
        }
        suggestionsLoading = true
        suggestions = []
        highlightedSuggestion = nil
        do {
            try await Task.sleep(nanoseconds: 250_000_000)
        } catch {
            return
        }
        guard !Task.isCancelled else { return }
        let assets = await client.assets(matching: searchQuery)
        guard !Task.isCancelled, query.trimmingCharacters(in: .whitespacesAndNewlines) == searchQuery else { return }
        suggestions = Array(assets.prefix(10))
        highlightedSuggestion = suggestions.isEmpty ? nil : 0
        suggestionsLoading = false
    }

    private func loadBars() async {
        guard let ticker = selectedTicker else {
            highlightedBar = nil
            bars = []
            return
        }
        highlightedBar = nil
        barsLoading = true
        bars = []
        let loadedBars = await client.bars(for: ticker, range: selectedRange)
        guard !Task.isCancelled, selectedTicker == ticker else { return }
        bars = loadedBars
        barsLoading = false
        resetChartView()
    }

    private func zoom(by multiplier: Double) {
        guard bars.count > 1 else { return }
        let fullDomain = chartDomainDuration
        let minimumDomain = max(fullDomain / 100, 60)
        visibleDomain = min(max(visibleDomain * multiplier, minimumDomain), fullDomain)
    }

    private func resetChartView() {
        visibleDomain = chartDomainDuration
        scrollPosition = bars.first?.date ?? Date()
    }

    private var chartDomainDuration: TimeInterval {
        guard let first = bars.first?.date, let last = bars.last?.date else { return 1 }
        return max(last.timeIntervalSince(first), 1)
    }
}

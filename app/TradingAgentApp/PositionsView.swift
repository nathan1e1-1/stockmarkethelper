import SwiftUI

struct PositionsView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        List {
            Section("Positions") {
                if let positions = client.status?.positions, !positions.isEmpty {
                    ForEach(positions, id: \.ticker) { p in
                        Text("\(p.ticker) · \(p.qty, specifier: "%.0f") @ $\(p.avg_entry_price, specifier: "%.2f")")
                    }
                } else {
                    Text("No open positions")
                }
            }
            Section("Decisions") {
                if let decisions = client.status?.decisions, !decisions.isEmpty {
                    ForEach(decisions, id: \.ticker) { d in
                        VStack(alignment: .leading) {
                            Text("\(d.ticker) — \(d.decision) (\(d.confidence, specifier: "%.2f"))")
                            Text(d.rationale).font(.caption).foregroundColor(.secondary)
                        }
                    }
                } else {
                    Text("No decisions yet")
                }
            }
        }
        .task { await client.refresh() }
    }
}

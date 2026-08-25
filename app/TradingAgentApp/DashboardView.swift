import SwiftUI

struct DashboardView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let eq = client.status?.equity {
                Text("Equity: $\(eq.equity, specifier: "%.2f")").font(.largeTitle)
                let pnl = (eq.equity / eq.day_start_equity - 1) * 100
                Text("Day P&L: \(pnl, specifier: "%+.2f")%").foregroundColor(pnl >= 0 ? .green : .red)
            } else {
                Text("Waiting for engine…")
            }
            if client.status?.kill_switch == true {
                Label("KILL SWITCH ENGAGED", systemImage: "exclamationmark.octagon.fill").foregroundColor(.red)
            }
            if client.status?.daily_stop == true {
                Label("Daily stop reached", systemImage: "stop.circle.fill").foregroundColor(.orange)
            }
        }
        .padding()
        .task { await client.refresh() }
    }
}

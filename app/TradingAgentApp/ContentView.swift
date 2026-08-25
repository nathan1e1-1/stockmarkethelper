import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            DashboardView().tabItem { Label("Dashboard", systemImage: "chart.line.uptrend.xyaxis") }
            ChartsView().tabItem { Label("Charts", systemImage: "chart.xyaxis.line") }
            PositionsView().tabItem { Label("Positions", systemImage: "list.bullet") }
            SummaryView().tabItem { Label("Summary", systemImage: "text.quote") }
        }
    }
}

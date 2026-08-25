import SwiftUI

struct SummaryView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        ScrollView {
            Text(client.summary.isEmpty ? "No summary yet — generated after market close." : client.summary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        }
        .task { await client.refresh() }
    }
}

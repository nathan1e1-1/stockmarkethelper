import SwiftUI

struct SummaryView: View {
    @ObservedObject private var client = EngineClient.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    SSectionLabel(text: "Daily summary")
                    Spacer()
                    Text("Generated after market close")
                        .font(.caption)
                        .foregroundStyle(Color.mutedForeground)
                }

                if client.summary.isEmpty {
                    SCard {
                        VStack(spacing: 12) {
                            Image(systemName: "text.quote")
                                .font(.system(size: 28))
                                .foregroundStyle(Color.mutedForeground)
                            Text("No summary yet")
                                .font(.title3.weight(.medium))
                                .foregroundStyle(Color.foreground)
                            Text("The agents write a post-market recap after the close, covering what went well, what didn't, and what to improve.")
                                .font(.callout)
                                .foregroundStyle(Color.mutedForeground)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 48)
                    }
                } else {
                    SCard {
                        Text(client.summary)
                            .font(.body)
                            .foregroundStyle(Color.foreground)
                            .lineSpacing(5)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(20)
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: 920, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color.background)
        .task {
            client.start()
            await client.refresh()
        }
    }
}

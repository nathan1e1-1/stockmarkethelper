import SwiftUI

struct SummaryView: View {
    @ObservedObject private var client = EngineClient.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    SectionTitle(text: "Daily summary")
                    Spacer()
                    Text("Generated after market close")
                        .font(.caption)
                        .foregroundColor(.textSecondary)
                }

                if client.summary.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "text.quote")
                            .font(.system(size: 28))
                            .foregroundColor(.textSecondary)
                        Text("No summary yet")
                            .font(.title3.weight(.medium))
                            .foregroundColor(.textPrimary)
                        Text("The agents write a post-market recap after the close, covering what went well, what didn't, and what to improve.")
                            .font(.callout)
                            .foregroundColor(.textSecondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 48)
                    .card()
                } else {
                    Text(client.summary)
                        .font(.body)
                        .foregroundColor(.textPrimary)
                        .lineSpacing(5)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .card()
                }
            }
            .padding(24)
            .frame(maxWidth: 920, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color.bg)
        .task {
            client.start()
            await client.refresh()
        }
    }
}

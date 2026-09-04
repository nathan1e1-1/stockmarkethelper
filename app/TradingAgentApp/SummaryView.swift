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
                .entrance()

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
                    .entrance(delay: 0.08)
                } else {
                    let sections = parseSummarySections(client.summary)

                    if sections.isStructured {
                        if !sections.glance.isEmpty {
                            summaryCard(title: "Today at a glance", lines: sections.glance)
                                .entrance(delay: 0.08)
                        }
                        if !sections.activity.isEmpty {
                            summaryCard(title: "Trading activity", lines: sections.activity)
                                .entrance(delay: 0.16)
                        }
                        if !sections.details.isEmpty {
                            summaryCard(title: "Account details", lines: sections.details)
                                .entrance(delay: 0.24)
                        }
                    } else {
                        summaryCard(title: "Account details", lines: sections.details)
                            .entrance(delay: 0.08)
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

    @ViewBuilder
    private func summaryCard(title: String, lines: [String]) -> some View {
        SCard {
            VStack(alignment: .leading, spacing: 8) {
                SSectionLabel(text: title)
                Text(lines.joined(separator: "\n"))
                    .font(.body)
                    .foregroundStyle(Color.foreground)
                    .lineSpacing(5)
                    .monospacedDigit()
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 4)
            }
            .padding(20)
        }
    }
}

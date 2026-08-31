import SwiftUI

struct ChatComposerState {
    var draft = ""
    var isLoading = false

    var canSubmit: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isLoading
    }
}

struct AITradeDeskView: View {
    @ObservedObject private var client = EngineClient.shared

    @State private var messages: [ChatMessage] = []
    @State private var composer = ChatComposerState()
    @State private var errorMessage: String?
    @State private var retryQuestion: String?

    private let starters = [
        "What is driving today’s P&L?",
        "Summarize my open risk.",
        "What do the latest trading decisions mean?",
    ]

    var body: some View {
        SCard {
            VStack(alignment: .leading, spacing: 16) {
                header
                conversation

                if let errorMessage {
                    errorCard(message: errorMessage)
                }

                composerView

                Text("Read-only informational analysis. No orders can be placed here.")
                    .font(.caption)
                    .foregroundStyle(Color.mutedForeground)
            }
            .padding(20)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("AI Trade Desk")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 3) {
            SCardHeader(
                title: "AI Trade Desk",
                subtitle: "Ask about the current account snapshot"
            )
            Text("Analysis only")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.mutedForeground)
        }
    }

    @ViewBuilder
    private var conversation: some View {
        if messages.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("Start with a question")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Color.foreground)
                Text("The assistant can explain account performance, open risk, and recent decisions using the current engine snapshot.")
                    .font(.caption)
                    .foregroundStyle(Color.mutedForeground)

                ForEach(starters, id: \.self) { starter in
                    Button {
                        submit(starter)
                    } label: {
                        HStack(spacing: 8) {
                            Text(starter)
                                .font(.caption.weight(.medium))
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                            Image(systemName: "arrow.up.right")
                                .font(.caption.weight(.semibold))
                        }
                        .foregroundStyle(Color.foreground)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.secondary)
                        .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(composer.isLoading)
                }
            }
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(messages) { message in
                        messageBubble(message)
                    }

                    if composer.isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Analysing the current account snapshot…")
                                .font(.caption)
                                .foregroundStyle(Color.mutedForeground)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .frame(maxHeight: 280)
        }
    }

    private func messageBubble(_ message: ChatMessage) -> some View {
        VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
            Text(message.role == .user ? "You" : "AI analysis")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Color.mutedForeground)
            Text(message.text)
                .font(.callout)
                .foregroundStyle(Color.foreground)
                .textSelection(.enabled)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
                .background(message.role == .user ? Color.secondary : Color.background)
                .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                        .stroke(Color.border, lineWidth: message.role == .user ? 0 : 1)
                )
        }
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    private func errorCard(message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Color.warn)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Assistant unavailable")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(Color.foreground)
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(Color.mutedForeground)
                }
            }
            SButton(title: "Retry", systemImage: "arrow.clockwise", variant: .outline, size: .sm) {
                retry()
            }
            .disabled(composer.isLoading || retryQuestion == nil)
        }
        .padding(12)
        .background(Color.warn.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                .stroke(Color.warn.opacity(0.4), lineWidth: 1)
        )
    }

    private var composerView: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Ask about your trades")
                .font(.callout.weight(.semibold))
                .foregroundStyle(Color.foreground)

            TextField("Ask about today’s trades or risk…", text: $composer.draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.callout)
                .foregroundStyle(Color.foreground)
                .lineLimit(2...4)
                .padding(10)
                .background(Color.background)
                .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                        .stroke(Color.border, lineWidth: 1)
                )
                .accessibilityLabel("Ask about your trades")

            HStack {
                Spacer()
                SButton(
                    title: composer.isLoading ? "Sending…" : "Send",
                    systemImage: composer.isLoading ? "hourglass" : "arrow.up",
                    size: .sm
                ) {
                    submit(composer.draft)
                }
                .disabled(!composer.canSubmit)
            }
        }
    }

    private func submit(_ question: String) {
        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuestion.isEmpty, !composer.isLoading else { return }

        messages.append(ChatMessage(role: .user, text: trimmedQuestion))
        composer.draft = ""
        errorMessage = nil
        retryQuestion = trimmedQuestion
        requestAnswer(for: trimmedQuestion)
    }

    private func retry() {
        guard let retryQuestion, !composer.isLoading else { return }
        errorMessage = nil
        requestAnswer(for: retryQuestion)
    }

    private func requestAnswer(for question: String) {
        composer.isLoading = true

        Task {
            do {
                let answer = try await client.ask(question)
                messages.append(ChatMessage(role: .assistant, text: answer))
                retryQuestion = nil
            } catch {
                errorMessage = error.localizedDescription
            }
            composer.isLoading = false
        }
    }
}

private struct ChatMessage: Identifiable {
    enum Role {
        case user
        case assistant
    }

    let id = UUID()
    let role: Role
    let text: String
}

import SwiftUI

extension Color {
    static let bg = Color(hex: 0x0B0F14)
    static let surface = Color(hex: 0x141B24)
    static let surfaceHigh = Color(hex: 0x1C2530)
    static let accent = Color(hex: 0x2DD4BF)
    static let textPrimary = Color(hex: 0xE6EDF3)
    static let textSecondary = Color(hex: 0x8B949E)
    static let gain = Color(hex: 0x3FB950)
    static let loss = Color(hex: 0xF85149)
    static let warn = Color(hex: 0xD29922)
    static let border = Color(hex: 0x2A333D)

    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }
}

struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(20)
            .background(Color.surface)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.border, lineWidth: 1)
            )
    }
}

extension View {
    func card() -> some View { modifier(CardModifier()) }
}

struct StatCard: View {
    let title: String
    let value: String
    var tint: Color = .textPrimary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundColor(.textSecondary)
            Text(value)
                .font(.title2.weight(.semibold))
                .monospacedDigit()
                .foregroundColor(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

struct SectionTitle: View {
    let text: String

    var body: some View {
        Text(text.uppercased())
            .font(.caption.weight(.semibold))
            .tracking(1.2)
            .foregroundColor(.textSecondary)
    }
}

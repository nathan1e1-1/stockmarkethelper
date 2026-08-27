import SwiftUI

// MARK: - Button (shadcn Button)

struct SButton: View {
    enum Variant { case `default`, secondary, outline, ghost, destructive }
    enum Size { case sm, md, lg }

    let title: String
    var systemImage: String? = nil
    var variant: Variant = .default
    var size: Size = .md
    var fullWidth = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let systemImage { Image(systemName: systemImage) }
                Text(title)
            }
            .font(font)
            .fontWeight(.medium)
            .foregroundStyle(foreground)
            .padding(.horizontal, horizontalPadding)
            .frame(height: height)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                    .stroke(borderColor, lineWidth: borderColor == .clear ? 0 : 1)
            )
        }
        .buttonStyle(PressableStyle())
    }

    private var foreground: Color {
        switch variant {
        case .default: return .primaryForeground
        case .secondary: return .foreground
        case .outline: return .foreground
        case .ghost: return .foreground
        case .destructive: return .white
        }
    }

    private var background: Color {
        switch variant {
        case .default: return .primary
        case .secondary: return .secondary
        case .outline, .ghost: return .clear
        case .destructive: return .destructive
        }
    }

    private var borderColor: Color {
        switch variant {
        case .outline: return .border
        default: return .clear
        }
    }

    private var font: Font {
        switch size {
        case .sm: return .caption
        case .md: return .callout
        case .lg: return .body
        }
    }

    private var horizontalPadding: CGFloat {
        switch size {
        case .sm: return 12
        case .md: return 16
        case .lg: return 20
        }
    }

    private var height: CGFloat {
        switch size {
        case .sm: return 28
        case .md: return 36
        case .lg: return 44
        }
    }
}

// MARK: - Card (shadcn Card)

struct SCard<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .background(Color.card)
            .clipShape(RoundedRectangle(cornerRadius: SRadius.lg, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SRadius.lg, style: .continuous)
                    .stroke(Color.border, lineWidth: 1)
            )
    }
}

struct SCardHeader: View {
    let title: String
    var subtitle: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundStyle(Color.foreground)
            if !subtitle.isEmpty {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(Color.mutedForeground)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Badge (shadcn Badge)

struct SBadge: View {
    enum Variant { case `default`, secondary, outline, destructive, success }

    let text: String
    var variant: Variant = .default

    var body: some View {
        Text(text)
            .font(.caption.weight(.medium))
            .foregroundStyle(foreground)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(background)
            .clipShape(Capsule())
            .overlay(Capsule().stroke(borderColor, lineWidth: borderColor == .clear ? 0 : 1))
    }

    private var foreground: Color {
        switch variant {
        case .default: return .primaryForeground
        case .secondary: return .foreground
        case .outline: return .foreground
        case .destructive: return .white
        case .success: return .white
        }
    }

    private var background: Color {
        switch variant {
        case .default: return .primary
        case .secondary: return .secondary
        case .outline: return .clear
        case .destructive: return .destructive
        case .success: return .gain
        }
    }

    private var borderColor: Color {
        switch variant {
        case .outline: return .border
        default: return .clear
        }
    }
}

// MARK: - Input (shadcn Input)

struct SInput: View {
    @Binding var text: String
    let placeholder: String
    var systemImage: String? = nil
    var onSubmit: () -> Void = {}

    var body: some View {
        HStack(spacing: 10) {
            if let systemImage {
                Image(systemName: systemImage).foregroundStyle(Color.mutedForeground)
            }
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(.body)
                .foregroundStyle(Color.foreground)
                .onSubmit(onSubmit)
        }
        .padding(.horizontal, 12)
        .frame(height: 36)
        .background(Color.background)
        .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                .stroke(Color.border, lineWidth: 1)
        )
    }
}

// MARK: - Alert (shadcn Alert)

struct SAlert: View {
    enum Variant { case `default`, destructive, warning, success }

    let icon: String
    let title: String
    var description: String = ""
    var variant: Variant = .default

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.callout)
                .foregroundStyle(iconColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Color.foreground)
                if !description.isEmpty {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(Color.mutedForeground)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(tint.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: SRadius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SRadius.md, style: .continuous)
                .stroke(tint.opacity(0.4), lineWidth: 1)
        )
    }

    private var tint: Color {
        switch variant {
        case .default: return .border
        case .destructive: return .destructive
        case .warning: return .warn
        case .success: return .gain
        }
    }

    private var iconColor: Color {
        switch variant {
        case .default: return .mutedForeground
        case .destructive: return .destructive
        case .warning: return .warn
        case .success: return .gain
        }
    }
}

// MARK: - Stat card

struct SStatCard: View {
    let title: String
    let value: String
    var tint: Color = .foreground

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(Color.mutedForeground)
            Text(value)
                .font(.title2.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(Color.card)
        .clipShape(RoundedRectangle(cornerRadius: SRadius.lg, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SRadius.lg, style: .continuous)
                .stroke(Color.border, lineWidth: 1)
        )
    }
}

// MARK: - Section heading

struct SSectionLabel: View {
    let text: String

    var body: some View {
        Text(text.uppercased())
            .font(.caption.weight(.semibold))
            .tracking(1.2)
            .foregroundStyle(Color.mutedForeground)
    }
}

// MARK: - Animation helpers

struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.9 : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

struct EntranceModifier: ViewModifier {
    @State private var visible = false
    var delay: Double = 0

    func body(content: Content) -> some View {
        content
            .opacity(visible ? 1 : 0)
            .offset(y: visible ? 0 : 8)
            .onAppear {
                withAnimation(.easeOut(duration: 0.3).delay(delay)) {
                    visible = true
                }
            }
    }
}

extension View {
    func entrance(delay: Double = 0) -> some View {
        modifier(EntranceModifier(delay: delay))
    }
}

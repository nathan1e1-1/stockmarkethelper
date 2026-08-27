import SwiftUI

// shadcn/ui "dark" theme tokens (zinc scale), ported to SwiftUI.
extension Color {
    static let background = Color(hex: 0x09090B)       // zinc-950
    static let foreground = Color(hex: 0xFAFAFA)       // zinc-50
    static let card = Color(hex: 0x09090B)
    static let muted = Color(hex: 0x27272A)            // zinc-800
    static let mutedForeground = Color(hex: 0xA1A1AA)  // zinc-400
    static let border = Color(hex: 0x27272A)
    static let primary = Color(hex: 0xFAFAFA)
    static let primaryForeground = Color(hex: 0x09090B)
    static let secondary = Color(hex: 0x27272A)
    static let accent = Color(hex: 0x27272A)
    static let destructive = Color(hex: 0xEF4444)      // red-500
    static let gain = Color(hex: 0x22C55E)             // green-500
    static let loss = Color(hex: 0xEF4444)
    static let warn = Color(hex: 0xEAB308)             // yellow-500
    static let ring = Color(hex: 0xA1A1AA)

    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }
}

enum SRadius {
    static let sm: CGFloat = 6
    static let md: CGFloat = 8
    static let lg: CGFloat = 12
}

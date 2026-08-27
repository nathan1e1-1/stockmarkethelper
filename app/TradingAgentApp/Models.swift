import Foundation

struct Equity: Codable {
    let equity: Double
    let day_start_equity: Double
    let peak_equity: Double
    let day: String
}

struct Position: Codable {
    let ticker: String
    let qty: Double
    let avg_entry_price: Double
}

struct Decision: Codable {
    let ticker: String
    let decision: String
    let rationale: String
    let confidence: Double
}

struct EngineStatus: Codable {
    let equity: Equity?
    let positions: [Position]
    let decisions: [Decision]
    let equity_history: [EquityPoint]
    let kill_switch: Bool
    let daily_stop: Bool
}

struct EquityPoint: Codable, Identifiable {
    let t: Double
    let equity: Double

    var id: Double { t }
    var date: Date { Date(timeIntervalSince1970: t) }
}

struct Bar: Codable, Identifiable {
    let t: String
    let o: Double
    let h: Double
    let l: Double
    let c: Double
    let v: Double

    var id: String { t }

    var date: Date {
        Bar.dateFormatter.date(from: t) ?? Date(timeIntervalSince1970: 0)
    }

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXXXX"
        return f
    }()

    enum CodingKeys: String, CodingKey {
        case t
        case o = "open"
        case h = "high"
        case l = "low"
        case c = "close"
        case v = "volume"
    }
}

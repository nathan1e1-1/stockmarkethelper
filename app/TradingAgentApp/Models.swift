import Foundation

struct Asset: Codable, Identifiable {
    let ticker: String
    let name: String

    var id: String { ticker }
}

struct AssetSearchResponse: Codable {
    let assets: [Asset]
}

enum ChartRange: String, CaseIterable, Codable, Identifiable {
    case oneDay = "1D"
    case fiveDays = "5D"
    case oneMonth = "1M"
    case sixMonths = "6M"
    case oneYear = "1Y"
    case max = "MAX"

    var id: String { rawValue }
}

struct ChatRequest: Codable {
    let question: String
}

struct ChatResponse: Codable {
    static let fallbackDisclaimer = "For informational purposes only — not investment advice. Use your own judgment."

    let answer: String
    let disclaimer: String
    let headline: String?
    let keyPoints: [String]
    let details: [String]

    private enum CodingKeys: String, CodingKey {
        case answer
        case disclaimer
        case headline
        case keyPoints = "key_points"
        case details
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        answer = try container.decode(String.self, forKey: .answer)
        disclaimer = try container.decodeIfPresent(String.self, forKey: .disclaimer) ?? Self.fallbackDisclaimer
        headline = try container.decodeIfPresent(String.self, forKey: .headline)
        keyPoints = try container.decodeIfPresent([String].self, forKey: .keyPoints) ?? []
        details = try container.decodeIfPresent([String].self, forKey: .details) ?? []
    }
}

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

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        equity = try c.decodeIfPresent(Equity.self, forKey: .equity)
        positions = try c.decodeIfPresent([Position].self, forKey: .positions) ?? []
        decisions = try c.decodeIfPresent([Decision].self, forKey: .decisions) ?? []
        equity_history = try c.decodeIfPresent([EquityPoint].self, forKey: .equity_history) ?? []
        kill_switch = try c.decodeIfPresent(Bool.self, forKey: .kill_switch) ?? false
        daily_stop = try c.decodeIfPresent(Bool.self, forKey: .daily_stop) ?? false
    }

    enum CodingKeys: String, CodingKey {
        case equity, positions, decisions
        case equity_history, kill_switch, daily_stop
    }
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

func nearestBar(to date: Date, in bars: [Bar]) -> Bar? {
    bars.min { lhs, rhs in
        abs(lhs.date.timeIntervalSince(date)) < abs(rhs.date.timeIntervalSince(date))
    }
}

func nearestEquityPoint(to date: Date, in points: [EquityPoint]) -> EquityPoint? {
    points.min { lhs, rhs in
        abs(lhs.date.timeIntervalSince(date)) < abs(rhs.date.timeIntervalSince(date))
    }
}

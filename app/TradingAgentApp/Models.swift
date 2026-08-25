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
    let kill_switch: Bool
    let daily_stop: Bool
}

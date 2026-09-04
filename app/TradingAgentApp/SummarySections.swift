import Foundation

struct SummarySections {
    var glance: [String] = []     // "Today at a glance"
    var activity: [String] = []   // "Trading activity"
    var details: [String] = []    // "Account details"
    var isStructured: Bool = false // true if at least one labelled section was recognized
}

private enum SummaryBucket {
    case glance
    case activity
    case details
}

private let glanceHeadings: [String] = [
    "Day P&L",
    "Today at a glance",
    "Today's P&L",
    "What went well",
    "What didn't go well",
    "Process Improvement",
]

private let activityHeadings: [String] = [
    "Closed trades",
    "Trading activity",
    "Decisions made",
    "Open positions at close",
    "Realized results",
    "Here are the realized results",
]

private let detailHeadings: [String] = [
    "Account details",
    "Account",
    "Equity",
]

func parseSummarySections(_ raw: String) -> SummarySections {
    var glances: [String] = []
    var activities: [String] = []
    var details: [String] = []

    var currentBucket: SummaryBucket = .details
    var hadAnyHeading = false

    for line in raw.components(separatedBy: .newlines) {
        if let bucket = bucket(forHeading: line) {
            hadAnyHeading = true
            currentBucket = bucket
            continue
        }

        switch currentBucket {
        case .glance: glances.append(line)
        case .activity: activities.append(line)
        case .details: details.append(line)
        }
    }

    guard hadAnyHeading else {
        return SummarySections(
            glance: [],
            activity: [],
            details: raw.isEmpty ? [] : [raw],
            isStructured: false
        )
    }

    return SummarySections(
        glance: trimmed(glances),
        activity: trimmed(activities),
        details: trimmed(details),
        isStructured: true
    )
}

private func trimmed(_ lines: [String]) -> [String] {
    var lines = lines
    while let first = lines.first, first.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        lines.removeFirst()
    }
    while let last = lines.last, last.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        lines.removeLast()
    }
    return lines
}

private func bucket(forHeading line: String) -> SummaryBucket? {
    let normalized = line
        .trimmingCharacters(in: CharacterSet(charactersIn: ":- \t"))
        .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        .lowercased()

    guard !normalized.isEmpty else { return nil }

    if glanceHeadings.contains(where: { $0.lowercased() == normalized }) {
        return .glance
    }
    if activityHeadings.contains(where: { $0.lowercased() == normalized }) {
        return .activity
    }
    if detailHeadings.contains(where: { $0.lowercased() == normalized }) {
        return .details
    }
    return nil
}

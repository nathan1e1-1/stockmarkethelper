import XCTest
@testable import TradingAgentApp

final class TradingAgentAppTests: XCTestCase {
    func testAssetSearchDecodesTickerAndName() throws {
        let data = #"{"assets":[{"ticker":"AAPL","name":"Apple Inc."}]}"#.data(using: .utf8)!

        let response = try JSONDecoder().decode(AssetSearchResponse.self, from: data)

        XCTAssertEqual(response.assets.first?.ticker, "AAPL")
        XCTAssertEqual(response.assets.first?.name, "Apple Inc.")
    }

    func testChartRangeOneYearEncodesWireValue() throws {
        let data = try JSONEncoder().encode(ChartRange.oneYear)

        XCTAssertEqual(String(decoding: data, as: UTF8.self), #""1Y""#)
    }

    func testChatResponseDecodesAnswerAndDisclosure() throws {
        let data = #"{"answer":"Your account has no open positions.","disclaimer":"For informational purposes only — not investment advice. Use your own judgment."}"#.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatResponse.self, from: data)

        XCTAssertEqual(response.answer, "Your account has no open positions.")
        XCTAssertEqual(response.disclaimer, "For informational purposes only — not investment advice. Use your own judgment.")
    }

    func testChatResponseDecodesLegacyAnswerWithFallbackDisclosure() throws {
        let data = #"{"answer":"Your account has no open positions."}"#.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatResponse.self, from: data)

        XCTAssertEqual(response.answer, "Your account has no open positions.")
        XCTAssertEqual(response.disclaimer, "For informational purposes only — not investment advice. Use your own judgment.")
    }

    func testChatResponseDecodesStructuredSections() throws {
        let data = #"{"answer":"Net P&L is up $1,200 today.","disclaimer":"For informational purposes only.","headline":"Net P&L is up $1,200 today.","key_points":["Apple gained $800","Tesla lost $200"],"details":["AAPL: +$800 from 100 shares","TSLA: -$200 from 50 shares"]}"#.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatResponse.self, from: data)

        XCTAssertEqual(response.headline, "Net P&L is up $1,200 today.")
        XCTAssertEqual(response.keyPoints, ["Apple gained $800", "Tesla lost $200"])
        XCTAssertEqual(response.details, ["AAPL: +$800 from 100 shares", "TSLA: -$200 from 50 shares"])
    }

    func testChatResponseDecodesLegacyWithoutStructuredSections() throws {
        let data = #"{"answer":"Your account has no open positions."}"#.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatResponse.self, from: data)

        XCTAssertEqual(response.answer, "Your account has no open positions.")
        XCTAssertNil(response.headline)
        XCTAssertEqual(response.keyPoints, [])
        XCTAssertEqual(response.details, [])
    }

    func testChatValidationDetailsProduceActionableQuestionMessage() {
        let arrayDetail = #"{"detail":[{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character"}]}"#.data(using: .utf8)!
        let objectDetail = #"{"detail":{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character"}}"#.data(using: .utf8)!

        XCTAssertEqual(EngineClient.serverErrorMessage(from: arrayDetail), "Enter a question between 1 and 2,000 characters.")
        XCTAssertEqual(EngineClient.serverErrorMessage(from: objectDetail), "Enter a question between 1 and 2,000 characters.")
    }

    func testNearestBarSelectsTheClosestTimestamp() {
        let first = Bar(t: "2026-08-28T14:00:00Z", o: 100, h: 102, l: 99, c: 101, v: 1000)
        let second = Bar(t: "2026-08-28T14:05:00Z", o: 101, h: 103, l: 100, c: 102, v: 1200)

        XCTAssertEqual(nearestBar(to: first.date.addingTimeInterval(230), in: [first, second])?.id, second.id)
    }

    func testNearestEquityPointSelectsTheClosestTimestamp() {
        let first = EquityPoint(t: 1_000, equity: 100_000)
        let second = EquityPoint(t: 1_300, equity: 100_200)

        XCTAssertEqual(nearestEquityPoint(to: Date(timeIntervalSince1970: 1_250), in: [first, second])?.id, second.id)
    }
}

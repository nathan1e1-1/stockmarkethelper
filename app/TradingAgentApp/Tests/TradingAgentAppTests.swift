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

    func testChatValidationDetailsProduceActionableQuestionMessage() {
        let arrayDetail = #"{"detail":[{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character"}]}"#.data(using: .utf8)!
        let objectDetail = #"{"detail":{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character"}}"#.data(using: .utf8)!

        XCTAssertEqual(EngineClient.serverErrorMessage(from: arrayDetail), "Enter a question between 1 and 2,000 characters.")
        XCTAssertEqual(EngineClient.serverErrorMessage(from: objectDetail), "Enter a question between 1 and 2,000 characters.")
    }
}

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

    func testChatResponseDecodesAnswer() throws {
        let data = #"{"answer":"Your account has no open positions."}"#.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(ChatResponse.self, from: data).answer, "Your account has no open positions.")
    }
}

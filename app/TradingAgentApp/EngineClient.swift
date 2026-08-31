import Foundation

enum EngineClientError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let message):
            return message
        }
    }
}

@MainActor
final class EngineClient: ObservableObject {
    static let shared = EngineClient()

    @Published var status: EngineStatus?
    @Published var summary: String = ""
    @Published var connected = false

    private let baseURL = URL(string: "http://127.0.0.1:8001")!
    private var pollTask: Task<Void, Never>?

    func start() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func refresh() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/status"))
            status = try JSONDecoder().decode(EngineStatus.self, from: data)
            let (sdata, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/summary"))
            summary = (try JSONDecoder().decode([String: String].self, from: sdata))["summary"] ?? ""
            connected = true
        } catch {
            connected = false
        }
    }

    func assets(matching query: String) async -> [Asset] {
        var comps = URLComponents(url: baseURL.appending(path: "/api/assets"), resolvingAgainstBaseURL: false)
        comps?.queryItems = [URLQueryItem(name: "query", value: query)]
        guard let url = comps?.url else { return [] }

        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard isSuccessful(response) else { return [] }
            return try JSONDecoder().decode(AssetSearchResponse.self, from: data).assets
        } catch {
            return []
        }
    }

    func bars(for ticker: String) async -> [Bar] {
        await bars(for: ticker, range: .oneDay)
    }

    func bars(for ticker: String, range: ChartRange) async -> [Bar] {
        var comps = URLComponents(url: baseURL.appending(path: "/api/bars"), resolvingAgainstBaseURL: false)
        comps?.queryItems = [
            URLQueryItem(name: "ticker", value: ticker),
            URLQueryItem(name: "range", value: range.rawValue),
        ]
        guard let url = comps?.url else { return [] }

        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard isSuccessful(response) else { return [] }
            let resp = try JSONDecoder().decode([String: [Bar]].self, from: data)
            return resp["bars"] ?? []
        } catch {
            return []
        }
    }

    func ask(_ question: String) async throws -> ChatResponse {
        var request = URLRequest(url: baseURL.appending(path: "/api/chat"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(ChatRequest(question: question))

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard isSuccessful(response) else {
                throw EngineClientError.message(Self.serverErrorMessage(from: data))
            }
            return try JSONDecoder().decode(ChatResponse.self, from: data)
        } catch let error as EngineClientError {
            throw error
        } catch is DecodingError {
            throw EngineClientError.message("The assistant returned an unexpected response. Please try again.")
        } catch {
            throw EngineClientError.message("Unable to reach the assistant. Please try again.")
        }
    }

    private func isSuccessful(_ response: URLResponse) -> Bool {
        guard let response = response as? HTTPURLResponse else { return false }
        return (200..<300).contains(response.statusCode)
    }

    nonisolated static func serverErrorMessage(from data: Data) -> String {
        if let response = try? JSONDecoder().decode(ServerErrorResponse.self, from: data),
           !response.detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return response.detail
        }

        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = payload["detail"] else {
            return "The assistant is temporarily unavailable. Please try again shortly."
        }

        if let validationErrors = detail as? [Any], !validationErrors.isEmpty {
            return "Enter a question between 1 and 2,000 characters."
        }
        if let validationError = detail as? [String: Any], !validationError.isEmpty {
            return "Enter a question between 1 and 2,000 characters."
        }

        return "The assistant is temporarily unavailable. Please try again shortly."
    }
}

private struct ServerErrorResponse: Decodable {
    let detail: String
}

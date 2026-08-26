import Foundation

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
}

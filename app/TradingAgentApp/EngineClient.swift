import Foundation

@MainActor
final class EngineClient: ObservableObject {
    @Published var status: EngineStatus?
    @Published var summary: String = ""
    private let baseURL = URL(string: "http://127.0.0.1:8000")!

    func refresh() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/status"))
            status = try JSONDecoder().decode(EngineStatus.self, from: data)
            let (sdata, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/summary"))
            summary = (try JSONDecoder().decode([String: String].self, from: sdata))["summary"] ?? ""
        } catch {
            // keep last known state on transient failure
        }
    }
}

import SwiftUI
import Charts

struct ChartsView: View {
    @State private var query = ""

    var body: some View {
        VStack {
            TextField("Search ticker…", text: $query)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 300)
            if query.isEmpty {
                Text("Enter a ticker to load its chart").foregroundColor(.secondary)
            } else {
                Chart {
                    PointMark(x: .value("t", 0), y: .value("price", 100))
                }
                .frame(height: 300)
            }
        }
        .padding()
    }
}

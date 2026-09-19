import Foundation
#if canImport(SwiftUI)
import SwiftUI

@MainActor
public final class StatusActionViewModel: ObservableObject {
    @Published public private(set) var status: SystemStatus?
    @Published public private(set) var isLoading = false
    @Published public private(set) var isSubmitting = false
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var lastDecisionID: String?

    private let flow: StatusActionFlow

    public init(flow: StatusActionFlow) {
        self.flow = flow
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            status = try await flow.fetchStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func submitAction(title: String) async {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "Action title is required."
            return
        }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            let decision = try await flow.submitAction(title: trimmed, sendToCouncil: true)
            lastDecisionID = decision.decisionID
            status = try await flow.fetchStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

public struct StatusActionView: View {
    @StateObject var model: StatusActionViewModel
    @State private var proposalTitle = ""

    public init(model: StatusActionViewModel) {
        _model = StateObject(wrappedValue: model)
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Pocket OS Status").font(.title3.bold())
            Group {
                if let status = model.status {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Status: \(status.status)")
                        Text("Ledger: \(status.ledger.integrity.rawValue) (\(status.ledger.valid ? "valid" : "invalid"))")
                        Text("Records: \(status.records)")
                        Text("Revision: \(status.revision)")
                    }
                    .font(.footnote.monospaced())
                } else if model.isLoading {
                    ProgressView("Loading status…")
                } else {
                    Text("No status loaded").foregroundColor(.secondary)
                }
            }

            TextField("Action title", text: $proposalTitle)
                .textFieldStyle(.roundedBorder)

            Button(model.isSubmitting ? "Submitting…" : "Submit Action") {
                Task { await model.submitAction(title: proposalTitle) }
            }
            .disabled(model.isSubmitting)

            if let decisionID = model.lastDecisionID {
                Text("Last decision: \(decisionID)")
                    .font(.caption.monospaced())
                    .foregroundColor(.secondary)
            }

            if let error = model.errorMessage {
                Text(error).font(.caption).foregroundColor(.red)
            }
        }
        .padding()
        .task { await model.load() }
    }
}
#endif

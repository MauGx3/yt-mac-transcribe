import Combine
import Foundation

@MainActor
final class TranscriptionViewModel: ObservableObject {
    enum State: Equatable {
        case idle
        case transcribing
        case awaitingReviewChoice(TranscriptFiles)
        case rewriting
        case completed(TranscriptFiles)
        case failed(String)
    }

    @Published private(set) var state: State = .idle
    private(set) var settings: AppSettings
    var canReview: Bool { !settings.rewriteCommand.isEmpty }
    private let runner: any TranscriptionRunning
    private var activeTask: Task<Void, Never>?
    private var activeOperationID: UUID?
    private var activeURL: String?

    init(settings: AppSettings, runner: any TranscriptionRunning = TranscriptionRunner()) {
        self.settings = settings
        self.runner = runner
    }

    func updateSettings(_ settings: AppSettings) {
        self.settings = settings
    }

    // [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review.
    // The operation ID is assigned synchronously when work is scheduled, so a
    // replaced task (even one cancelled before its body runs) can never pass
    // `isCurrent` and clobber `activeTask` or `state` of the newer request.
    func begin(url: String) {
        let operationID = replaceActiveOperation()
        activeTask = Task { await transcribe(url: url, operationID: operationID) }
    }

    func start(url: String) async {
        await transcribe(url: url, operationID: replaceActiveOperation())
    }

    private func replaceActiveOperation() -> UUID {
        activeTask?.cancel()
        activeTask = nil
        let operationID = UUID()
        activeOperationID = operationID
        return operationID
    }

    private func isCurrent(_ operationID: UUID) -> Bool {
        activeOperationID == operationID && !Task.isCancelled
    }

    private func finish(_ operationID: UUID, with newState: State) {
        guard isCurrent(operationID) else { return }
        activeTask = nil
        state = newState
    }

    private func transcribe(url: String, operationID: UUID) async {
        guard isCurrent(operationID) else { return }
        activeURL = url
        state = .transcribing
        do {
            let files = try await runner.transcribe(url: url, settings: settings)
            finish(operationID, with: .awaitingReviewChoice(files))
        } catch {
            finish(operationID, with: .failed(error.localizedDescription))
        }
    }

    func declineReview() {
        guard case let .awaitingReviewChoice(files) = state else { return }
        state = .completed(files)
    }

    func beginReview() {
        guard case .awaitingReviewChoice = state else { return }
        let operationID = replaceActiveOperation()
        activeTask = Task { await review(operationID: operationID) }
    }

    func acceptReview() async {
        guard case .awaitingReviewChoice = state else { return }
        await review(operationID: replaceActiveOperation())
    }

    private func review(operationID: UUID) async {
        guard isCurrent(operationID),
              case let .awaitingReviewChoice(originals) = state,
              let url = activeURL else { return }
        guard !settings.rewriteCommand.isEmpty else {
            finish(operationID, with: .failed("Set YTT_REWRITE_COMMAND or configure a local rewrite command in Settings first."))
            return
        }
        state = .rewriting
        do {
            let files = try await runner.review(url: url, settings: settings)
            finish(operationID, with: .completed(TranscriptFiles(original: originals.original, reviewed: files.reviewed)))
        } catch {
            finish(operationID, with: .failed(error.localizedDescription))
        }
    }

    func cancel() {
        activeOperationID = nil
        activeTask?.cancel()
        activeTask = nil
        state = .failed("Transcription was cancelled.")
    }
}

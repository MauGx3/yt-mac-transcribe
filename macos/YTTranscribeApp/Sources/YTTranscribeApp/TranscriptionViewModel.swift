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

    func begin(url: String) {
        activeTask?.cancel()
        activeTask = Task { await start(url: url) }
    }

    func start(url: String) async {
        activeURL = url
        let operationID = UUID()
        activeOperationID = operationID
        state = .transcribing
        do {
            let files = try await runner.transcribe(url: url, settings: settings)
            guard activeOperationID == operationID, !Task.isCancelled else { return }
            activeTask = nil
            state = .awaitingReviewChoice(files)
        } catch {
            guard activeOperationID == operationID else { return }
            activeTask = nil
            state = .failed(error.localizedDescription)
        }
    }

    func declineReview() {
        guard case let .awaitingReviewChoice(files) = state else { return }
        state = .completed(files)
    }

    func beginReview() {
        guard case .awaitingReviewChoice = state else { return }
        activeTask?.cancel()
        activeTask = Task { await acceptReview() }
    }

    func acceptReview() async {
        guard case let .awaitingReviewChoice(originals) = state, let url = activeURL else { return }
        guard !settings.rewriteCommand.isEmpty else {
            state = .failed("Set YTT_REWRITE_COMMAND or configure a local rewrite command in Settings first.")
            return
        }
        let operationID = UUID()
        activeOperationID = operationID
        state = .rewriting
        do {
            let files = try await runner.review(url: url, settings: settings)
            guard activeOperationID == operationID, !Task.isCancelled else { return }
            activeTask = nil
            state = .completed(TranscriptFiles(original: originals.original, reviewed: files.reviewed))
        } catch {
            guard activeOperationID == operationID else { return }
            activeTask = nil
            state = .failed(error.localizedDescription)
        }
    }

    func cancel() {
        activeOperationID = nil
        activeTask?.cancel()
        activeTask = nil
        state = .failed("Transcription was cancelled.")
    }
}

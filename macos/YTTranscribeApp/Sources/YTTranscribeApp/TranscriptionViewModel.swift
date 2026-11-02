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
    private var activeURL: String?

    init(settings: AppSettings, runner: any TranscriptionRunning = TranscriptionRunner()) {
        self.settings = settings
        self.runner = runner
    }

    func updateSettings(_ settings: AppSettings) {
        self.settings = settings
    }

    func start(url: String) async {
        activeURL = url
        state = .transcribing
        do {
            let files = try await runner.transcribe(url: url, settings: settings)
            state = .awaitingReviewChoice(files)
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func declineReview() {
        guard case let .awaitingReviewChoice(files) = state else { return }
        state = .completed(files)
    }

    func acceptReview() async {
        guard case let .awaitingReviewChoice(originals) = state, let url = activeURL else { return }
        guard !settings.rewriteCommand.isEmpty else {
            state = .failed("Set YTT_REWRITE_COMMAND or configure a local rewrite command in Settings first.")
            return
        }
        state = .rewriting
        do {
            let files = try await runner.review(url: url, settings: settings)
            state = .completed(TranscriptFiles(original: originals.original, reviewed: files.reviewed))
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func cancel() {
        activeTask?.cancel()
        activeTask = nil
        state = .failed("Transcription was cancelled.")
    }
}

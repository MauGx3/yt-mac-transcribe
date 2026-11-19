import Foundation
import Observation

@MainActor
@Observable
final class TranscriptionViewModel {
    enum State: Equatable {
        case idle
        case transcribing
        case awaitingReviewChoice(TranscriptFiles)
        case rewriting
        case completed(TranscriptFiles)
        case completedBatch(BatchSummary)
        case failed(String)
    }

    struct BatchSummary: Equatable {
        let kind: RunKind
        let requested: Int
        let files: [TranscriptFiles]
    }

    private(set) var state: State = .idle
    /// The latest line `ytt` printed while working, e.g. "[asr] downloading audio…".
    private(set) var progress: String?
    private(set) var formats: [OutputFormat]
    private(set) var settings: AppSettings
    var canReview: Bool { !settings.rewriteCommand.isEmpty }
    private let runner: any TranscriptionRunning
    private var activeTask: Task<Void, Never>?
    private var activeOperationID: UUID?
    private var activeURL: String?
    private var activeRecordID: UUID?
    private let library: LibraryStore?

    /// `library == nil` disables history (used by tests and previews).
    init(settings: AppSettings, runner: any TranscriptionRunning = TranscriptionRunner(), library: LibraryStore? = nil) {
        self.settings = settings
        self.formats = settings.effectiveFormats
        self.runner = runner
        self.library = library
        runner.setProgressHandler { [weak self] line in
            Task { @MainActor [weak self] in self?.receiveProgress(line) }
        }
    }

    private func receiveProgress(_ line: String) {
        switch state {
        case .transcribing, .rewriting: progress = line
        default: break
        }
    }

    func updateSettings(_ settings: AppSettings) {
        self.settings = settings
        formats = settings.effectiveFormats
    }

    /// Chooses the output formats for later runs and remembers the choice.
    func setFormats(_ newFormats: [OutputFormat]) {
        settings.formats = OutputFormat.normalized(newFormats)
        formats = settings.formats
        settings.persist()
    }

    /// Transcribes several videos, or every video of a playlist.
    func beginBatch(urls: [String], playlist: Bool) {
        let operationID = replaceActiveOperation()
        activeTask = Task { await runBatch(urls: urls, playlist: playlist, operationID: operationID) }
    }

    func startBatch(urls: [String], playlist: Bool) async {
        await runBatch(urls: urls, playlist: playlist, operationID: replaceActiveOperation())
    }

    private func runBatch(urls: [String], playlist: Bool, operationID: UUID) async {
        guard isCurrent(operationID) else { return }
        guard !urls.isEmpty else {
            finish(operationID, with: .failed("Enter at least one URL."))
            return
        }
        activeURL = nil
        activeRecordID = nil
        state = .transcribing
        let kind: RunKind = playlist ? .playlist : .batch
        do {
            let groups = try await runner.transcribeMany(urls: urls, playlist: playlist, settings: settings)
            // The files exist even if the run was cancelled meanwhile, so
            // they belong in the library either way.
            for group in groups {
                library?.add(TranscriptRecord.make(files: group, sourceURL: urls[0], kind: kind))
            }
            finish(operationID, with: .completedBatch(BatchSummary(kind: kind, requested: urls.count, files: groups)))
        } catch {
            finish(operationID, with: .failed(error.localizedDescription))
        }
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
        progress = nil
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
        progress = nil
        state = newState
    }

    private func transcribe(url: String, operationID: UUID) async {
        guard isCurrent(operationID) else { return }
        activeURL = url
        activeRecordID = nil
        state = .transcribing
        do {
            let files = try await runner.transcribe(url: url, settings: settings)
            if let library {
                let record = TranscriptRecord.make(files: files, sourceURL: url, kind: .single)
                activeRecordID = record.id
                library.add(record)
            }
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
            let files = try await runner.review(files: originals, url: url, settings: settings)
            if let id = activeRecordID, var record = library?.record(id: id) {
                record.reviewed = files.reviewed
                record.reviewFile = files.review
                library?.update(record)
            }
            finish(operationID, with: .completed(TranscriptFiles(original: originals.original, reviewed: files.reviewed, review: files.review)))
        } catch {
            finish(operationID, with: .failed(error.localizedDescription))
        }
    }

    /// Called when the review screen saves the Reviewed copy.
    func reviewSaved(reviewFile: URL, copy: URL) {
        library?.markReviewed(reviewFile: reviewFile, copy: copy)
    }

    func cancel() {
        activeOperationID = nil
        activeTask?.cancel()
        activeTask = nil
        progress = nil
        state = .failed("Transcription was cancelled.")
    }
}

import Foundation
import XCTest
@testable import YTTranscribeApp

final class TranscriptionViewModelTests: XCTestCase {
    @MainActor
    func testStartMovesToAwaitingReviewAndRetainsOriginal() async throws {
        let original = URL(fileURLWithPath: "/tmp/original.txt")
        let runner = StubRunner(transcriptionResult: TranscriptFiles(original: original))
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner)
        await model.start(url: "https://youtu.be/example")
        XCTAssertEqual(model.state, .awaitingReviewChoice(TranscriptFiles(original: original)))
    }

    @MainActor
    func testDeclineReviewCompletesWithOriginalOnly() async throws {
        let original = URL(fileURLWithPath: "/tmp/original.txt")
        let runner = StubRunner(transcriptionResult: TranscriptFiles(original: original))
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner)
        await model.start(url: "https://youtu.be/example")
        model.declineReview()
        XCTAssertEqual(model.state, .completed(TranscriptFiles(original: original)))
        XCTAssertEqual(runner.reviewCalls, 0)
    }

    @MainActor
    func testAcceptReviewCompletesWithBothPaths() async throws {
        let original = URL(fileURLWithPath: "/tmp/original.txt")
        let reviewed = URL(fileURLWithPath: "/tmp/original.rewritten.txt")
        let runner = StubRunner(transcriptionResult: TranscriptFiles(original: original), reviewResult: TranscriptFiles(original: original, reviewed: reviewed))
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner)
        await model.start(url: "https://youtu.be/example")
        await model.acceptReview()
        XCTAssertEqual(model.state, .completed(TranscriptFiles(original: original, reviewed: reviewed)))
        XCTAssertEqual(runner.reviewCalls, 1)
    }

    @MainActor
    func testReviewChoiceOnlyAppearsAfterOriginalSuccess() async {
        let runner = StubRunner()
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner)
        XCTAssertEqual(model.state, .idle)
        await model.start(url: "https://youtu.be/example")
        guard case .awaitingReviewChoice = model.state else { return XCTFail("Review choice should follow original success") }
    }

    func testRunnerErrorMovesToFailed() async {
        let runner = StubRunner(error: TestFailure.expected)
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner)
        await model.start(url: "https://youtu.be/example")
        guard case .failed = model.state else { return XCTFail("Expected failed state") }
    }
}

private enum TestFailure: LocalizedError {
    case expected
    var errorDescription: String? { "expected failure" }
}

private final class StubRunner: TranscriptionRunning {
    let transcriptionResult: TranscriptFiles
    let reviewResult: TranscriptFiles?
    let error: Error?
    private(set) var reviewCalls = 0

    init(transcriptionResult: TranscriptFiles = TranscriptFiles(original: URL(fileURLWithPath: "/tmp/original.txt")), reviewResult: TranscriptFiles? = nil, error: Error? = nil) {
        self.transcriptionResult = transcriptionResult
        self.reviewResult = reviewResult
        self.error = error
    }

    func transcribe(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        if let error { throw error }
        return transcriptionResult
    }

    func review(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        reviewCalls += 1
        if let error { throw error }
        return reviewResult ?? transcriptionResult
    }
}

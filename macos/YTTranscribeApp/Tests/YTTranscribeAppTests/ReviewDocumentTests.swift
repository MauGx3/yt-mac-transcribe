import Foundation
import XCTest
@testable import YTTranscribeApp

final class ReviewDocumentTests: XCTestCase {
    /// Written by `ytt.review.build_review` for a two-segment transcript.
    private let fixture = #"""
    {"version": 1, "video_id": "v", "title": "Talk", "url": "u", "original_engine": "asr", "stats": {"segments": 2, "changed": 1, "flagged": 1, "has_confidence": true}, "segments": [{"index": 0, "start_ms": 0, "end_ms": 900, "original": "their going home now", "enhanced": "They're going home, now", "hunks": [{"op": "replace", "orig": [0, 1], "new": [0, 1], "orig_text": "their", "new_text": "They're", "flags": ["ai_unsure"]}, {"op": "replace", "orig": [2, 3], "new": [2, 3], "orig_text": "home", "new_text": "home,", "flags": []}], "flags": [{"start": 0, "end": 7, "kind": "ai_unsure", "score": 0.3}]}, {"index": 1, "start_ms": 61000, "end_ms": 62000, "original": "ok", "enhanced": "ok", "hunks": [], "flags": []}]}
    """#

    private func document() throws -> ReviewDocument {
        try JSONDecoder().decode(ReviewDocument.self, from: Data(fixture.utf8))
    }

    func testDecodesStatsHunksAndFlags() throws {
        let doc = try document()
        XCTAssertEqual(doc.title, "Talk")
        XCTAssertEqual(doc.stats.changed, 1)
        XCTAssertTrue(doc.stats.hasConfidence)
        let first = doc.segments[0]
        XCTAssertTrue(first.isFlagged)
        XCTAssertTrue(first.hunks[0].isAIUnsure)
        XCTAssertFalse(first.hunks[0].isUnclearAudio)
        XCTAssertFalse(first.hunks[1].isFlagged)
        XCTAssertFalse(doc.segments[1].isChanged)
    }

    func testAcceptingEverythingGivesEnhancedText() throws {
        let doc = try document()
        let decisions = ReviewDecisions()
        XCTAssertEqual(decisions.reviewedText(for: doc), "They're going home, now\nok\n")
    }

    func testRejectingOneChangeKeepsOriginalWordsThere() throws {
        let doc = try document()
        var decisions = ReviewDecisions()
        decisions.set(HunkID(segment: 0, hunk: 0), accepted: false)
        XCTAssertEqual(decisions.text(for: doc.segments[0]), "their going home, now")
        decisions.set(HunkID(segment: 0, hunk: 1), accepted: false)
        XCTAssertEqual(decisions.text(for: doc.segments[0]), "their going home now")
    }

    func testAcceptAllUnflaggedLeavesUnsureRejectionsAlone() throws {
        let doc = try document()
        var decisions = ReviewDecisions()
        decisions.set(HunkID(segment: 0, hunk: 0), accepted: false)
        decisions.set(HunkID(segment: 0, hunk: 1), accepted: false)
        decisions.acceptAllUnflagged(in: doc)
        XCTAssertFalse(decisions.isAccepted(HunkID(segment: 0, hunk: 0)))
        XCTAssertTrue(decisions.isAccepted(HunkID(segment: 0, hunk: 1)))
    }

    func testReviewedFileSitsNextToReviewFile() {
        let review = URL(fileURLWithPath: "/tmp/out/My Talk.review.json")
        XCTAssertEqual(ReviewDocument.reviewedURL(for: review).path, "/tmp/out/My Talk.reviewed.txt")
    }

    @MainActor
    func testSaveWritesReviewedCopy() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        let reviewFile = dir.appendingPathComponent("Talk.review.json")
        try Data(fixture.utf8).write(to: reviewFile)

        let model = try ReviewViewModel(reviewFile: reviewFile)
        model.decisions.set(HunkID(segment: 0, hunk: 0), accepted: false)
        model.save()

        let saved = try XCTUnwrap(model.savedURL)
        XCTAssertEqual(saved.lastPathComponent, "Talk.reviewed.txt")
        XCTAssertEqual(try String(contentsOf: saved, encoding: .utf8), "their going home, now\nok\n")
        XCTAssertEqual(model.visibleSegments.map(\.index), [0])
    }

    func testRunnerPicksUpReviewFilePrintedLast() throws {
        let original = URL(fileURLWithPath: "/tmp/Talk.txt")
        let enhanced = URL(fileURLWithPath: "/tmp/Talk.rewritten.txt")
        let review = URL(fileURLWithPath: "/tmp/Talk.review.json")
        let files = try TranscriptionRunner.files(from: [original, enhanced, review], mode: .review)
        XCTAssertEqual(files.reviewed, enhanced)
        XCTAssertEqual(files.review, review)
        let older = try TranscriptionRunner.files(from: [original, enhanced], mode: .review)
        XCTAssertNil(older.review)
    }
}

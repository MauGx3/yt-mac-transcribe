import Foundation
import XCTest
@testable import YTTranscribeApp

final class LibraryTests: XCTestCase {
    private func temporaryDirectory() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        return dir
    }

    func testURLInputSkipsBlankLinesAndComments() {
        let text = "https://youtu.be/a\n\n  https://youtu.be/b  # second\n# only a comment\n"
        XCTAssertEqual(URLInput.parse(text), ["https://youtu.be/a", "https://youtu.be/b"])
    }

    func testFormatNormalizationOrdersDedupesAndDefaultsToTxt() {
        XCTAssertEqual(OutputFormat.normalized([.md, .srt, .md]), [.srt, .md])
        XCTAssertEqual(OutputFormat.normalized([]), [.txt])
        XCTAssertEqual(OutputFormat.parse("srt, bogus,txt"), [.txt, .srt])
    }

    func testFileNameParsingExtractsVideoID() {
        let parsed = TranscriptRecord.parseFileName(URL(fileURLWithPath: "/tmp/My Talk [dQw4w9WgXcQ].txt"))
        XCTAssertEqual(parsed.title, "My Talk")
        XCTAssertEqual(parsed.videoID, "dQw4w9WgXcQ")
        let plain = TranscriptRecord.parseFileName(URL(fileURLWithPath: "/tmp/My Talk.txt"))
        XCTAssertEqual(plain.title, "My Talk")
        XCTAssertNil(plain.videoID)
    }

    func testRecordUsesVideoIDForSourceURLInPlaylists() {
        let files = TranscriptFiles(original: URL(fileURLWithPath: "/tmp/A [dQw4w9WgXcQ].txt"), extras: [URL(fileURLWithPath: "/tmp/A [dQw4w9WgXcQ].srt")])
        let record = TranscriptRecord.make(files: files, sourceURL: "https://youtube.com/playlist?list=PL1", kind: .playlist)
        XCTAssertEqual(record.sourceURL, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        XCTAssertEqual(record.formats, ["txt", "srt"])
    }

    func testBatchArgumentsPassURLsFormatsAndPlaylistFlag() {
        var settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        settings.formats = [.srt, .txt]
        XCTAssertEqual(
            TranscriptionRunner.batchArguments(urls: ["u1", "u2"], playlist: false, settings: settings),
            ["u1", "u2", "-f", "txt", "srt", "-o", "/tmp/out", "--engine", "auto", "--model", "small.en"]
        )
        XCTAssertEqual(
            TranscriptionRunner.batchArguments(urls: ["list"], playlist: true, settings: settings),
            ["--playlist", "list", "-f", "txt", "srt", "-o", "/tmp/out", "--engine", "auto", "--model", "small.en"]
        )
    }

    func testGroupsSplitPathsPerVideo() {
        let paths = ["a.txt", "a.srt", "b.txt", "b.srt"].map { URL(fileURLWithPath: "/tmp/\($0)") }
        let groups = TranscriptionRunner.groups(from: paths, formatCount: 2)
        XCTAssertEqual(groups.map(\.original.lastPathComponent), ["a.txt", "b.txt"])
        XCTAssertEqual(groups.map { $0.extras.map(\.lastPathComponent) }, [["a.srt"], ["b.srt"]])
    }

    func testReviewWithMultipleFormatsPicksFirstRewrittenFile() throws {
        let paths = ["a.txt", "a.srt", "a.rewritten.txt", "a.rewritten.srt"].map { URL(fileURLWithPath: "/tmp/\($0)") }
        let files = try TranscriptionRunner.files(from: paths, mode: .review, formatCount: 2)
        XCTAssertEqual(files.original.lastPathComponent, "a.txt")
        XCTAssertEqual(files.extras.map(\.lastPathComponent), ["a.srt"])
        XCTAssertEqual(files.reviewed?.lastPathComponent, "a.rewritten.txt")
    }

    @MainActor
    func testLibraryPersistsAndReloads() throws {
        let file = try temporaryDirectory().appendingPathComponent("library.json")
        let store = LibraryStore(fileURL: file)
        store.add(TranscriptRecord.make(files: TranscriptFiles(original: URL(fileURLWithPath: "/tmp/One.txt")), sourceURL: "https://youtu.be/one", kind: .single))
        let reloaded = LibraryStore(fileURL: file)
        XCTAssertEqual(reloaded.records.map(\.title), ["One"])
    }

    @MainActor
    func testSearchMatchesTitleURLAndTranscriptText() throws {
        let dir = try temporaryDirectory()
        let transcript = dir.appendingPathComponent("Lecture.txt")
        try "the mitochondria is the powerhouse".write(to: transcript, atomically: true, encoding: .utf8)
        let store = LibraryStore(fileURL: nil)
        store.add(TranscriptRecord.make(files: TranscriptFiles(original: transcript), sourceURL: "https://youtu.be/abc", kind: .single))
        XCTAssertEqual(store.search("lecture", includeContents: false).count, 1)
        XCTAssertEqual(store.search("youtu.be/abc", includeContents: false).count, 1)
        XCTAssertEqual(store.search("mitochondria", includeContents: false).count, 0)
        XCTAssertEqual(store.search("MITOCHONDRIA", includeContents: true).count, 1)
        XCTAssertEqual(store.search("", includeContents: false).count, 1)
    }

    @MainActor
    func testSingleRunIsRecordedAndReviewAttachesToSameRecord() async {
        let original = URL(fileURLWithPath: "/tmp/Talk.txt")
        let reviewed = URL(fileURLWithPath: "/tmp/Talk.rewritten.txt")
        let runner = StubRunner(transcriptionResult: TranscriptFiles(original: original), reviewResult: TranscriptFiles(original: original, reviewed: reviewed))
        let library = LibraryStore(fileURL: nil)
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/tmp/ytt"), rewriteCommand: ["local"], outputDirectory: URL(fileURLWithPath: "/tmp"))
        let model = TranscriptionViewModel(settings: settings, runner: runner, library: library)
        await model.start(url: "https://youtu.be/talk")
        XCTAssertEqual(library.records.count, 1)
        XCTAssertNil(library.records[0].reviewed)
        await model.acceptReview()
        XCTAssertEqual(library.records.count, 1)
        XCTAssertEqual(library.records[0].reviewed, reviewed)
    }

    @MainActor
    func testBatchRecordsEveryVideoAndReportsSummary() async {
        let runner = StubRunner()
        runner.batchResult = [
            TranscriptFiles(original: URL(fileURLWithPath: "/tmp/A [aaaaaaaaaaa].txt")),
            TranscriptFiles(original: URL(fileURLWithPath: "/tmp/B [bbbbbbbbbbb].txt")),
        ]
        let library = LibraryStore(fileURL: nil)
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: runner, library: library)
        await model.startBatch(urls: ["u1", "u2", "u3"], playlist: false)
        XCTAssertEqual(library.records.count, 2)
        XCTAssertEqual(runner.batchCalls.first?.urls, ["u1", "u2", "u3"])
        guard case let .completedBatch(summary) = model.state else { return XCTFail("Expected batch summary") }
        XCTAssertEqual(summary.requested, 3)
        XCTAssertEqual(summary.files.count, 2)
    }

    @MainActor
    func testEmptyBatchFails() async {
        let model = TranscriptionViewModel(settings: AppSettings.defaults, runner: StubRunner())
        await model.startBatch(urls: [], playlist: false)
        guard case .failed = model.state else { return XCTFail("Expected failure") }
    }

    @MainActor
    func testReviewFileAndReviewedCopyMoveRecordThroughStatuses() async {
        let original = URL(fileURLWithPath: "/tmp/Talk.txt")
        let enhanced = URL(fileURLWithPath: "/tmp/Talk.rewritten.txt")
        let review = URL(fileURLWithPath: "/tmp/Talk.review.json")
        let runner = StubRunner(transcriptionResult: TranscriptFiles(original: original),
                                reviewResult: TranscriptFiles(original: original, reviewed: enhanced, review: review))
        let library = LibraryStore(fileURL: nil)
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/tmp/ytt"), rewriteCommand: ["local"], outputDirectory: URL(fileURLWithPath: "/tmp"))
        let model = TranscriptionViewModel(settings: settings, runner: runner, library: library)
        await model.start(url: "https://youtu.be/talk")
        XCTAssertEqual(library.records[0].reviewStatus, .notEnhanced)
        await model.acceptReview()
        XCTAssertEqual(library.records[0].reviewFile, review)
        XCTAssertEqual(library.records[0].reviewStatus, .needsReview)
        guard case let .completed(files) = model.state else { return XCTFail("Expected completed") }
        XCTAssertEqual(files.review, review)

        let copy = URL(fileURLWithPath: "/tmp/Talk.reviewed.txt")
        model.reviewSaved(reviewFile: review, copy: copy)
        XCTAssertEqual(library.records[0].reviewedCopy, copy)
        XCTAssertEqual(library.records[0].reviewStatus, .reviewed)
        XCTAssertTrue(library.records[0].allFiles.contains(copy))
    }

    func testLibrarySavedBeforeReviewFieldsStillLoads() throws {
        let json = #"[{"id":"7C4C3F4E-8A0B-4C47-9B49-7B0F1B7E2A11","title":"Old","sourceURL":"u","createdAt":"2026-11-01T10:00:00Z","kind":"single","files":["file:///tmp/Old.txt"],"reviewed":"file:///tmp/Old.rewritten.txt"}]"#
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let records = try decoder.decode([TranscriptRecord].self, from: Data(json.utf8))
        XCTAssertEqual(records.count, 1)
        XCTAssertNil(records[0].reviewFile)
        XCTAssertNil(records[0].reviewedCopy)
        XCTAssertEqual(records[0].reviewStatus, .notEnhanced)
    }

    @MainActor
    func testCorruptLibraryIsMovedAsideAndGoodRecordsKept() throws {
        let dir = try temporaryDirectory()
        let file = dir.appendingPathComponent("library.json")
        let good = """
        {"id":"\(UUID().uuidString)","title":"Good","sourceURL":"https://youtu.be/a","createdAt":"2026-11-19T00:00:00Z","kind":"single","files":["file:///tmp/a.txt"]}
        """
        try Data("[\(good), {\"broken\": true}]".utf8).write(to: file)
        let store = LibraryStore(fileURL: file)
        XCTAssertEqual(store.records.map(\.title), ["Good"])
        let names = try FileManager.default.contentsOfDirectory(atPath: dir.path)
        XCTAssertTrue(names.contains { $0.hasPrefix("library.corrupt-") }, "\(names)")
        XCTAssertFalse(names.contains("library.json"))
    }
}

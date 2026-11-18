import Foundation
import XCTest
@testable import YTTranscribeApp

final class TranscriptionRunnerTests: XCTestCase {
    func testTranscribeArgumentsKeepURLAsSingleArgument() {
        let url = "https://example.invalid/video title?x=$(touch sentinel)"
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        let args = TranscriptionRunner.arguments(for: .transcribe, url: url, settings: settings)
        XCTAssertEqual(args, [url, "-f", "txt", "-o", "/tmp/out", "--engine", "auto", "--model", "small.en"])
        XCTAssertEqual(args.first, url)
    }

    func testEngineAndModelArePassedToYtt() {
        var settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        settings.engine = .mlx
        settings.model = "large-v3-turbo"
        let args = TranscriptionRunner.arguments(for: .transcribe, url: "https://example.invalid/v", settings: settings)
        XCTAssertEqual(Array(args.suffix(4)), ["--engine", "mlx", "--model", "large-v3-turbo"])
    }

    func testReviewAddsRewriteArgumentsAsSeparateTokens() {
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: ["/opt/local/model runner", "--model", "small model"], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        let args = TranscriptionRunner.arguments(for: .review, url: "https://example.invalid/watch?v=abc", settings: settings)
        XCTAssertEqual(Array(args.suffix(4)), ["--rewrite-command", "/opt/local/model runner", "--model", "small model"])
    }

    func testOutputPairDoesNotMisclassifyOriginalTitleEndingInRewritten() throws {
        let original = URL(fileURLWithPath: "/tmp/lecture.rewritten.txt")
        let reviewed = URL(fileURLWithPath: "/tmp/lecture.rewritten.rewritten.txt")
        let files = try TranscriptionRunner.files(from: [original, reviewed], mode: .review)
        XCTAssertEqual(files.original, original)
        XCTAssertEqual(files.reviewed, reviewed)
    }

    func testNonzeroExitIncludesStderr() async throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temp) }
        let script = temp.appendingPathComponent("failing-ytt")
        try "#!/bin/sh\necho diagnostic-from-test >&2\nexit 7\n".write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let settings = AppSettings(yttExecutable: script, rewriteCommand: [], outputDirectory: temp)
        do {
            _ = try await TranscriptionRunner().transcribe(url: "https://example.invalid", settings: settings)
            XCTFail("Expected command failure")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("diagnostic-from-test"))
        }
    }

    func testBatchKeepsWrittenFilesWhenSomeVideosFail() async throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temp) }
        let written = temp.appendingPathComponent("good.txt")
        try "text".write(to: written, atomically: true, encoding: .utf8)
        let script = temp.appendingPathComponent("partial-ytt")
        try "#!/bin/sh\necho '\(written.path)'\necho 'one video failed' >&2\nexit 3\n"
            .write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let settings = AppSettings(yttExecutable: script, rewriteCommand: [], outputDirectory: temp)
        let groups = try await TranscriptionRunner().transcribeMany(
            urls: ["https://example.invalid/a", "https://example.invalid/b"], playlist: false, settings: settings)
        XCTAssertEqual(groups.map(\.original.lastPathComponent), ["good.txt"])
    }

    func testSingleVideoStillFailsOnPartialExitCode() async throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temp) }
        let script = temp.appendingPathComponent("partial-ytt")
        try "#!/bin/sh\nexit 3\n".write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let settings = AppSettings(yttExecutable: script, rewriteCommand: [], outputDirectory: temp)
        do {
            _ = try await TranscriptionRunner().transcribe(url: "https://example.invalid", settings: settings)
            XCTFail("Expected command failure")
        } catch {}
    }

    func testMissingOutputIsFailure() async throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temp) }
        let script = temp.appendingPathComponent("successful-ytt")
        try "#!/bin/sh\nexit 0\n".write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let settings = AppSettings(yttExecutable: script, rewriteCommand: [], outputDirectory: temp)
        do {
            _ = try await TranscriptionRunner().transcribe(url: "https://example.invalid", settings: settings)
            XCTFail("Expected missing output validation failure")
        } catch {
            XCTAssertTrue(error.localizedDescription.localizedCaseInsensitiveContains("output"))
        }
    }

    // [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review.
    func testProcessEnvironmentPrependsToolDirectoriesWithoutDuplicates() {
        let env = TranscriptionRunner.processEnvironment(base: ["PATH": "/usr/bin:/custom/bin", "HOME": "/Users/test"])
        let entries = env["PATH"]?.split(separator: ":").map(String.init) ?? []
        XCTAssertEqual(entries.first, "/opt/homebrew/bin")
        XCTAssertTrue(entries.contains("/custom/bin"))
        XCTAssertEqual(entries.filter { $0 == "/usr/bin" }.count, 1)
        XCTAssertEqual(env["HOME"], "/Users/test")
    }

    func testProcessEnvironmentIncludesPipxBinDirectory() {
        // `pipx install mlx-whisper` (as the README suggests) puts tools in ~/.local/bin,
        // which a Finder-launched app does not have on PATH.
        let env = TranscriptionRunner.processEnvironment(base: ["PATH": "/usr/bin", "HOME": "/Users/test"])
        let entries = env["PATH"]?.split(separator: ":").map(String.init) ?? []
        XCTAssertTrue(entries.contains("/Users/test/.local/bin"))
        XCTAssertLessThan(entries.firstIndex(of: "/Users/test/.local/bin")!, entries.firstIndex(of: "/usr/bin")!)
    }

    func testExecuteDoesNotDeadlockOnOutputLargerThanPipeBuffer() async throws {
        // 256 KB on each stream: far past the ~64 KB pipe buffer.
        let script = "head -c 262144 /dev/zero | tr '\\0' a; head -c 262144 /dev/zero | tr '\\0' b >&2"
        let result = try await TranscriptionRunner.execute(
            executable: URL(fileURLWithPath: "/bin/sh"),
            arguments: ["-c", script]
        )
        XCTAssertEqual(result.status, 0)
        XCTAssertEqual(result.stdout.count, 262_144)
        XCTAssertEqual(result.stderr.count, 262_144)
    }
}

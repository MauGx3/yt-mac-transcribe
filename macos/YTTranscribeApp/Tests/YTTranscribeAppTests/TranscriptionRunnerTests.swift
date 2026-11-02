import Foundation
import XCTest
@testable import YTTranscribeApp

final class TranscriptionRunnerTests: XCTestCase {
    func testTranscribeArgumentsKeepURLAsSingleArgument() {
        let url = "https://example.invalid/video title?x=$(touch sentinel)"
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        let args = TranscriptionRunner.arguments(for: .transcribe, url: url, settings: settings)
        XCTAssertEqual(args, [url, "-f", "txt", "-o", "/tmp/out"])
        XCTAssertEqual(args.first, url)
    }

    func testReviewAddsRewriteArgumentsAsSeparateTokens() {
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/usr/bin/true"), rewriteCommand: ["/opt/local/model runner", "--model", "small model"], outputDirectory: URL(fileURLWithPath: "/tmp/out"))
        let args = TranscriptionRunner.arguments(for: .review, url: "https://example.invalid/watch?v=abc", settings: settings)
        XCTAssertEqual(Array(args.suffix(4)), ["--rewrite-command", "/opt/local/model runner", "--model", "small model"])
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
}

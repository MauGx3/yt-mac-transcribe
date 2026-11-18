import Foundation
import XCTest
@testable import YTTranscribeApp

final class BenchmarkTests: XCTestCase {
    private let sample = """
    {
      "version": 1,
      "system": {"chip": "Apple M2", "ram_gb": 16, "os_version": "15.1", "apple_silicon": true},
      "sample": {"source": "demo", "words": 200, "duration_s": 61.5},
      "asr": [
        {"engine": "mlx", "model": "small.en", "status": "ok", "seconds": 4.2, "realtime_x": 14.6, "wer": 0.015},
        {"engine": "whisper-cpp", "model": "tiny.en", "status": "not_downloaded", "reason": "not downloaded"}
      ],
      "llm": [
        {"model": "mlx-community/Qwen2.5-3B-Instruct-4bit", "status": "ok", "seconds": 20.1,
         "wer": 0.01, "strict": 0.04, "size_gb": 1.7}
      ],
      "recommendation": {
        "asr": {"engine": "mlx", "model": "small.en", "measured": true, "reason": "best"},
        "llm": {"model": "mlx-community/Qwen2.5-3B-Instruct-4bit", "measured": true, "reason": "best"}
      }
    }
    """

    func testDecodesDemoReport() throws {
        let report = try BenchmarkReport.decode(Data(sample.utf8))
        XCTAssertEqual(report.system.ramGb, 16)
        XCTAssertEqual(report.sample.durationS, 61.5)
        XCTAssertEqual(report.asr.count, 2)
        XCTAssertTrue(report.asr[0].isMeasured)
        XCTAssertEqual(report.asr[0].realtimeX, 14.6)
        XCTAssertFalse(report.asr[1].isMeasured)
        XCTAssertEqual(report.llm[0].shortName, "Qwen2.5-3B-Instruct-4bit")
        XCTAssertEqual(report.recommendation.asr.model, "small.en")
        XCTAssertNil(report.llmNote)
    }

    func testFormatting() {
        XCTAssertEqual(BenchmarkReport.percent(0.015), "1.5%")
        XCTAssertEqual(BenchmarkReport.percent(nil), "–")
        XCTAssertEqual(BenchmarkReport.seconds(4.25), "4.2 s")
    }

    func testArgumentsWithoutRewriteCommandSkipLLMs() {
        let settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/tmp/ytt"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp"))
        XCTAssertEqual(BenchmarkRunner.arguments(settings: settings, download: false), ["demo", "--json", "--no-pick", "--quiet", "--asr-only"])
    }

    func testArgumentsPassRewriteCommandLast() {
        let settings = AppSettings(
            yttExecutable: URL(fileURLWithPath: "/tmp/ytt"),
            rewriteCommand: ["python3", "rw.py", "--model", "x"],
            outputDirectory: URL(fileURLWithPath: "/tmp")
        )
        XCTAssertEqual(
            BenchmarkRunner.arguments(settings: settings, download: true),
            ["demo", "--json", "--no-pick", "--quiet", "--download", "--runner", "python3", "rw.py", "--model", "x"]
        )
    }

    func testRewriteCommandModelReplacement() {
        XCTAssertEqual(AppSettings.rewriteCommand(["python3", "rw.py", "--model", "old"], settingModel: "new"), ["python3", "rw.py", "--model", "new"])
        XCTAssertEqual(AppSettings.rewriteCommand(["rw", "--model=old"], settingModel: "new"), ["rw", "--model=new"])
        XCTAssertEqual(AppSettings.rewriteCommand(["rw"], settingModel: "new"), ["rw", "--model", "new"])
        XCTAssertEqual(AppSettings.rewriteCommand(["rw", "--model"], settingModel: "new"), ["rw", "--model", "new"])
    }

    @MainActor
    func testApplyBenchmarkChoiceUpdatesSettings() {
        let settings = AppSettings(
            yttExecutable: URL(fileURLWithPath: "/tmp/ytt"),
            rewriteCommand: ["rw", "--model", "old"],
            outputDirectory: URL(fileURLWithPath: "/tmp")
        )
        let suite = "BenchmarkTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = TranscriptionViewModel(settings: settings)
        model.applyBenchmarkChoice(engine: "mlx", model: "large-v3-turbo", llmModel: "new", defaults: defaults)
        XCTAssertEqual(model.settings.engine, .mlx)
        XCTAssertEqual(model.settings.model, "large-v3-turbo")
        XCTAssertEqual(model.settings.rewriteCommand, ["rw", "--model", "new"])
        XCTAssertEqual(defaults.string(forKey: "asrModel"), "large-v3-turbo")
    }
}

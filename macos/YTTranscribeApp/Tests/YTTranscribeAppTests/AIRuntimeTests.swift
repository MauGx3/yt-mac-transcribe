// [AI-GENERATED] Claude Code agent; pending human review.
import Foundation
import XCTest
@testable import YTTranscribeApp

final class AIRuntimeTests: XCTestCase {
    private var temp: URL!

    override func setUpWithError() throws {
        temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temp)
    }

    /// A layout in a temp folder with a fake uv, locks and runner.
    private func makeLayout(bundled: Bool = true) throws -> AIRuntimeLayout {
        let resources = temp.appendingPathComponent("Resources/AIRuntime", isDirectory: true)
        let uv = temp.appendingPathComponent("Helpers/uv")
        if bundled {
            try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: uv.deletingLastPathComponent(), withIntermediateDirectories: true)
            try "enhance==1\n".write(to: resources.appendingPathComponent("requirements-enhance.txt"), atomically: true, encoding: .utf8)
            try "enhance==1\nspeech==1\n".write(to: resources.appendingPathComponent("requirements-speech.txt"), atomically: true, encoding: .utf8)
            try "".write(to: resources.appendingPathComponent("rewrite_with_local_model.py"), atomically: true, encoding: .utf8)
            try makeExecutable(uv)
        }
        return AIRuntimeLayout(
            root: temp.appendingPathComponent("Support/AIRuntime", isDirectory: true),
            cache: temp.appendingPathComponent("Caches/uv", isDirectory: true),
            uv: bundled ? uv : nil,
            resources: bundled ? resources : nil
        )
    }

    private func makeExecutable(_ url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "#!/bin/sh\nexit 0\n".write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
    }

    private func install(_ layout: AIRuntimeLayout, components: [AIComponent], digest: String? = nil) throws {
        try makeExecutable(layout.python)
        let lock = layout.lockFile(for: Set(components))!
        try AIRuntime.writeManifest(
            AIRuntimeManifest(lockDigest: digest ?? AIRuntime.digest(of: lock)!, components: components, installedAt: Date(), uvVersion: AIRuntime.uvVersion),
            layout: layout
        )
    }

    // MARK: Status

    func testStatusWithoutBundledInstallerIsUnavailable() throws {
        let layout = try makeLayout(bundled: false)
        XCTAssertEqual(AIRuntime.status(layout: layout), .unavailable)
    }

    func testStatusBeforeInstallIsNotInstalled() throws {
        let layout = try makeLayout()
        XCTAssertEqual(AIRuntime.status(layout: layout), .notInstalled)
    }

    func testStatusAfterInstallIsReady() throws {
        let layout = try makeLayout()
        try install(layout, components: [.enhancement])
        XCTAssertEqual(AIRuntime.status(layout: layout), .ready(components: [.enhancement], outdated: false))
    }

    func testNewerBundledLockMarksRuntimeOutdated() throws {
        let layout = try makeLayout()
        try install(layout, components: [.enhancement, .speech], digest: "old")
        XCTAssertEqual(AIRuntime.status(layout: layout), .ready(components: [.enhancement, .speech], outdated: true))
    }

    func testManifestWithoutPythonIsDamaged() throws {
        let layout = try makeLayout()
        try install(layout, components: [.enhancement])
        try FileManager.default.removeItem(at: layout.python)
        XCTAssertEqual(AIRuntime.status(layout: layout), .damaged)
    }

    // MARK: Commands

    func testManagedRewriteCommandOnlyWhenReady() throws {
        let layout = try makeLayout()
        XCTAssertNil(AIRuntime.managedRewriteCommand(layout: layout, model: nil))
        try install(layout, components: [.enhancement])
        let runner = layout.runner!.path
        XCTAssertEqual(AIRuntime.managedRewriteCommand(layout: layout, model: nil), [layout.python.path, "-I", runner])
        XCTAssertEqual(AIRuntime.managedRewriteCommand(layout: layout, model: "org/m"), [layout.python.path, "-I", runner, "--model", "org/m"])
    }

    func testInstallStepsPinHashesAndAvoidUserWideChanges() throws {
        let layout = try makeLayout()
        let steps = try XCTUnwrap(AIRuntime.installSteps(layout: layout, components: [.enhancement]))
        XCTAssertEqual(steps.count, 4)
        XCTAssertTrue(steps[0].arguments.contains("--no-bin"))
        XCTAssertTrue(steps[1].arguments.contains(layout.staging.path))
        XCTAssertTrue(steps[1].arguments.contains("--relocatable"))
        let sync = steps[2].arguments
        XCTAssertEqual(Array(sync.prefix(3)), ["pip", "sync", layout.lockFile(for: [.enhancement])!.path])
        XCTAssertTrue(sync.contains("--require-hashes"))
        XCTAssertEqual(sync[sync.firstIndex(of: "--only-binary")! + 1], ":all:")
        XCTAssertEqual(steps[3].executable, layout.staging.appendingPathComponent("bin/python"))
        XCTAssertFalse(steps[3].arguments.joined().contains("mlx_whisper"))
    }

    func testSpeechUsesTheSpeechLockAndChecksMLXWhisper() throws {
        let layout = try makeLayout()
        let steps = try XCTUnwrap(AIRuntime.installSteps(layout: layout, components: [.enhancement, .speech]))
        XCTAssertTrue(steps[2].arguments.contains(layout.resources!.appendingPathComponent("requirements-speech.txt").path))
        XCTAssertTrue(steps[3].arguments.joined(separator: " ").contains("import mlx_whisper"))
    }

    func testEnvironmentKeepsUvInsideTheAppFolders() throws {
        let layout = try makeLayout()
        let env = AIRuntime.environment(layout: layout, base: ["PATH": "/usr/bin", "PYTHONPATH": "/x", "VIRTUAL_ENV": "/v"])
        XCTAssertNil(env["PYTHONPATH"])
        XCTAssertNil(env["VIRTUAL_ENV"])
        XCTAssertEqual(env["UV_PYTHON_INSTALL_DIR"], layout.pythonInstalls.path)
        XCTAssertEqual(env["UV_CACHE_DIR"], layout.cache.path)
        XCTAssertEqual(env["UV_NO_CONFIG"], "1")
        XCTAssertEqual(env["PATH"], "/usr/bin")
    }

    func testPromoteStagingReplacesTheOldEnvironment() throws {
        let layout = try makeLayout()
        try makeExecutable(layout.python)
        try makeExecutable(layout.staging.appendingPathComponent("bin/marker"))
        try AIRuntime.promoteStaging(layout: layout)
        let fm = FileManager.default
        XCTAssertTrue(fm.fileExists(atPath: layout.binDirectory.appendingPathComponent("marker").path))
        XCTAssertFalse(fm.fileExists(atPath: layout.python.path))
        XCTAssertFalse(fm.fileExists(atPath: layout.staging.path))
        XCTAssertFalse(fm.fileExists(atPath: layout.root.appendingPathComponent("venv.old").path))
    }

    func testDownloadFractionReadsProgressLinesOnly() {
        XCTAssertEqual(AIRuntime.downloadFraction(fromLine: #"{"event": "progress", "done": 25, "total": 100}"#), 0.25)
        XCTAssertNil(AIRuntime.downloadFraction(fromLine: #"{"event": "start", "total": 100}"#))
        XCTAssertNil(AIRuntime.downloadFraction(fromLine: #"{"event": "progress", "done": 1, "total": 0}"#))
        XCTAssertNil(AIRuntime.downloadFraction(fromLine: "Fetching 5 files"))
    }

    // MARK: Integration with the runner and settings

    func testCustomCommandWinsOverManagedCommand() {
        var settings = AppSettings(yttExecutable: URL(fileURLWithPath: "/tmp/ytt"), rewriteCommand: [], outputDirectory: URL(fileURLWithPath: "/tmp"))
        XCTAssertEqual(settings.effectiveRewriteCommand, [])
        settings.managedRewriteCommand = ["/rt/python", "-I", "/app/runner.py"]
        XCTAssertEqual(settings.effectiveRewriteCommand, ["/rt/python", "-I", "/app/runner.py"])
        let args = TranscriptionRunner.arguments(for: .review, url: "https://example.invalid/v", settings: settings)
        XCTAssertEqual(Array(args.suffix(4)), ["--rewrite-command", "/rt/python", "-I", "/app/runner.py"])
        settings.rewriteCommand = ["custom"]
        XCTAssertEqual(settings.effectiveRewriteCommand, ["custom"])
    }

    func testPyzRunsWithFirstAvailablePython() throws {
        let pyz = URL(fileURLWithPath: "/Applications/App.app/Contents/Resources/ytt.pyz")
        let launch = try TranscriptionRunner.launchCommand(
            executable: pyz, arguments: ["--version"],
            pythonCandidates: ["/missing/python", "/opt/homebrew/bin/python3"],
            isExecutable: { $0 == "/opt/homebrew/bin/python3" }
        )
        XCTAssertEqual(launch.executable.path, "/opt/homebrew/bin/python3")
        XCTAssertEqual(launch.arguments, [pyz.path, "--version"])
    }

    func testPyzWithoutAnyPythonExplainsHowToGetOne() {
        XCTAssertThrowsError(try TranscriptionRunner.launchCommand(
            executable: URL(fileURLWithPath: "/x/ytt.pyz"), arguments: [],
            pythonCandidates: ["/missing"], isExecutable: { _ in false }
        )) { error in
            XCTAssertTrue(error.localizedDescription.contains("Set Up On-Device AI"))
        }
    }

    func testNonPyzExecutableRunsDirectly() throws {
        let launch = try TranscriptionRunner.launchCommand(
            executable: URL(fileURLWithPath: "/opt/homebrew/bin/ytt"), arguments: ["a"],
            pythonCandidates: [], isExecutable: { _ in false }
        )
        XCTAssertEqual(launch.executable.path, "/opt/homebrew/bin/ytt")
        XCTAssertEqual(launch.arguments, ["a"])
    }

    func testProcessEnvironmentPutsRuntimeBinAfterHomebrewAndBeforePipx() {
        let env = TranscriptionRunner.processEnvironment(
            base: ["PATH": "/usr/bin", "HOME": "/Users/test"],
            runtimeBin: URL(fileURLWithPath: "/rt/venv/bin")
        )
        let entries = env["PATH"]?.split(separator: ":").map(String.init) ?? []
        guard let runtime = entries.firstIndex(of: "/rt/venv/bin") else {
            return XCTFail("runtime bin missing from PATH: \(entries)")
        }
        XCTAssertLessThan(entries.firstIndex(of: "/usr/local/bin")!, runtime)
        XCTAssertLessThan(runtime, entries.firstIndex(of: "/Users/test/.local/bin")!)
    }

    // MARK: Streaming

    func testLineStreamingSplitsOnNewlinesAndCarriageReturns() async throws {
        final class Lines: @unchecked Sendable {
            private let lock = NSLock()
            private var items: [String] = []
            func add(_ line: String) { lock.lock(); items.append(line); lock.unlock() }
            var all: [String] { lock.lock(); defer { lock.unlock() }; return items }
        }
        let lines = Lines()
        let result = try await LineStreamingProcess.run(
            executable: URL(fileURLWithPath: "/bin/sh"),
            arguments: ["-c", "printf 'one\\ntwo\\rthree'; printf 'err\\n' >&2; exit 3"],
            environment: [:],
            onLine: { lines.add($0) }
        )
        XCTAssertEqual(result.status, 3)
        XCTAssertEqual(Set(lines.all), ["one", "two", "three", "err"])
        XCTAssertEqual(Set(result.lastLines), ["one", "two", "three", "err"])
    }
}

import Foundation
import XCTest
@testable import YTTranscribeApp

final class EnhancementSetupTests: XCTestCase {
    private func temporaryRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("EnhancementSetupTests-\(UUID().uuidString)/Application Support/AI", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root.deletingLastPathComponent().deletingLastPathComponent()) }
        return root
    }

    func testCommandLineRoundTripsPathsWithSpacesAndQuotes() {
        let tokens = ["/Users/me/Library/Application Support/YTTranscribe/AI/venv/bin/python",
                      "plain", "say \"hi\"", "back\\slash", "it's", ""]
        let line = AppSettings.commandLine(tokens)
        XCTAssertEqual(AppSettings.parseCommand(line), tokens)
        XCTAssertEqual(AppSettings.commandLine(["ollama", "run", "llama3"]), "ollama run llama3")
    }

    func testPersistKeepsBuiltInCommandIntact() {
        let suite = "EnhancementSetupTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        var settings = AppSettings.load(from: defaults, environment: [:])
        let setup = EnhancementSetup(root: URL(fileURLWithPath: "/tmp/With Space/AI", isDirectory: true))
        settings.rewriteCommand = setup.command + ["--model", "mlx-community/Llama-3.2-3B-Instruct-4bit"]
        settings.persist(to: defaults)
        XCTAssertEqual(AppSettings.load(from: defaults, environment: [:]).rewriteCommand, settings.rewriteCommand)
    }

    func testIsBuiltInAllowsExtraArguments() {
        let setup = EnhancementSetup(root: URL(fileURLWithPath: "/tmp/AI", isDirectory: true))
        XCTAssertTrue(setup.isBuiltIn(setup.command))
        XCTAssertTrue(setup.isBuiltIn(setup.command + ["--model", "x"]))
        XCTAssertFalse(setup.isBuiltIn(["/usr/bin/python3", setup.runner.path]))
        XCTAssertFalse(setup.isBuiltIn([setup.python.path]))
    }

    func testModelPrefersCommandThenEnvironmentThenConfigThenDefault() throws {
        let root = try temporaryRoot()
        let setup = EnhancementSetup(root: root)
        let config = root.appendingPathComponent("config.json")
        let missingConfig = ["YTT_CONFIG": root.appendingPathComponent("missing.json").path]

        XCTAssertEqual(setup.model(for: setup.command + ["--model", "a/b"], environment: ["YTT_LLM_MODEL": "c/d"]), "a/b")
        // Another tool's --model is not the helper's model.
        XCTAssertEqual(setup.model(for: ["ollama", "--model", "a/b"], environment: missingConfig), EnhancementSetup.defaultModel)
        XCTAssertEqual(setup.model(for: [], environment: ["YTT_LLM_MODEL": "c/d"]), "c/d")

        try Data(#"{"llm_model": "e/f"}"#.utf8).write(to: config)
        XCTAssertEqual(setup.model(for: [], environment: ["YTT_CONFIG": config.path]), "e/f")
        XCTAssertEqual(setup.model(for: [], environment: missingConfig), EnhancementSetup.defaultModel)
    }

    func testIsInstalledNeedsMarkerPythonAndRunner() throws {
        let root = try temporaryRoot()
        let setup = EnhancementSetup(root: root)
        let fm = FileManager.default
        XCTAssertFalse(setup.isInstalled)

        try fm.createDirectory(at: setup.python.deletingLastPathComponent(), withIntermediateDirectories: true)
        fm.createFile(atPath: setup.python.path, contents: Data(), attributes: [.posixPermissions: 0o755])
        try setup.copyRunner(from: setup.python)
        XCTAssertFalse(setup.isInstalled, "no marker yet: setup did not finish")

        fm.createFile(atPath: setup.marker.path, contents: Data("{}".utf8))
        XCTAssertTrue(setup.isInstalled)
    }

    func testEnvironmentKeepsUVInsideRootAndDropsOtherPythons() {
        let setup = EnhancementSetup(root: URL(fileURLWithPath: "/tmp/AI", isDirectory: true))
        let env = setup.environment(base: ["PATH": "/usr/bin", "VIRTUAL_ENV": "/other", "PYTHONPATH": "/x"])
        XCTAssertEqual(env["UV_PYTHON_INSTALL_DIR"], "/tmp/AI/python")
        XCTAssertEqual(env["UV_CACHE_DIR"], "/tmp/AI/cache")
        XCTAssertNil(env["VIRTUAL_ENV"])
        XCTAssertNil(env["PYTHONPATH"])
        XCTAssertEqual(env["PATH"], "/usr/bin")
    }

    func testModelCacheFolderFollowsHuggingFaceLayout() {
        let model = "mlx-community/Qwen2.5-3B-Instruct-4bit"
        XCTAssertEqual(
            EnhancementSetup.modelCacheFolder(model, environment: ["HF_HOME": "/hf"]).path,
            "/hf/hub/models--mlx-community--Qwen2.5-3B-Instruct-4bit"
        )
        XCTAssertEqual(
            EnhancementSetup.modelCacheFolder(model, environment: ["HF_HUB_CACHE": "/cache", "HF_HOME": "/hf"]).path,
            "/cache/models--mlx-community--Qwen2.5-3B-Instruct-4bit"
        )
        XCTAssertTrue(EnhancementSetup.isLocalModel("/models/qwen"))
        XCTAssertFalse(EnhancementSetup.isLocalModel(model))
    }

    func testChecksumIsLowercaseHex() {
        XCTAssertEqual(
            EnhancementSetup.sha256(Data("abc".utf8)),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
    }

    @MainActor
    func testRemoveTurnsOffEnhancementOnlyWhenBuiltInWasInUse() throws {
        let root = try temporaryRoot()
        let suite = "EnhancementSetupTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let setup = EnhancementSetup(root: root)

        var settings = AppSettings.load(from: defaults, environment: [:])
        settings.rewriteCommand = setup.command
        let model = TranscriptionViewModel(settings: settings, enhancement: EnhancementInstaller(setup: setup))
        try model.removeEnhancement(defaults: defaults)
        XCTAssertEqual(model.settings.rewriteCommand, [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))

        settings.rewriteCommand = ["ollama", "run", "llama3"]
        let custom = TranscriptionViewModel(settings: settings, enhancement: EnhancementInstaller(setup: setup))
        try custom.removeEnhancement(defaults: defaults)
        XCTAssertEqual(custom.settings.rewriteCommand, ["ollama", "run", "llama3"])
    }
}

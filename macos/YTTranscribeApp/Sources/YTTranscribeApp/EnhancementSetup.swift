// [AI-GENERATED] Claude Code agent (claude-opus-5-5); pending human review.
import CryptoKit
import Foundation
import Observation

/// Where the built-in AI enhancement lives and how it is put together.
///
/// Everything goes in one folder, `~/Library/Application Support/YTTranscribe/AI`:
/// a pinned `uv` (checked against its published SHA-256), a private Python
/// that `uv` downloads, a virtual environment with a pinned MLX-LM, and a copy
/// of the rewrite helper bundled in the app. Nothing is installed system-wide,
/// and deleting the folder removes all of it. The language model goes to the
/// shared Hugging Face cache, where `ytt` and the Benchmark also look for it.
struct EnhancementSetup: Equatable {
    static let uvVersion = "0.13.9"
    static let uvSHA256 = "5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca"
    static let uvURL = URL(string: "https://github.com/astral-sh/uv/releases/download/\(uvVersion)/uv-aarch64-apple-darwin.tar.gz")!
    static let pythonVersion = "3.12"
    static let mlxLMRequirement = "mlx-lm==0.32.2"
    /// Same default as `tools/rewrite_with_local_model.py`.
    static let defaultModel = "mlx-community/Qwen2.5-3B-Instruct-4bit"

    let root: URL

    static let standard = EnhancementSetup(
        root: FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/YTTranscribe/AI", isDirectory: true)
    )

    var uv: URL { root.appendingPathComponent("bin/uv") }
    var venv: URL { root.appendingPathComponent("venv", isDirectory: true) }
    var python: URL { venv.appendingPathComponent("bin/python") }
    var runner: URL { root.appendingPathComponent("rewrite_with_local_model.py") }
    /// Written last, so a half-finished install never counts as installed.
    var marker: URL { root.appendingPathComponent("installed.json") }

    /// The helper copied into the app bundle by `scripts/bundle-ytt.sh`.
    static var bundledRunner: URL? {
        Bundle.main.url(forResource: "rewrite_with_local_model", withExtension: "py")
    }

    /// MLX runs only on Apple silicon.
    static var isSupported: Bool {
        #if arch(arm64)
        return true
        #else
        return false
        #endif
    }

    var isInstalled: Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: marker.path)
            && fm.isExecutableFile(atPath: python.path)
            && fm.fileExists(atPath: runner.path)
    }

    /// The rewrite command for Settings: the private Python running the helper.
    var command: [String] { [python.path, runner.path] }

    /// Whether `command` runs this setup; extra arguments such as `--model` are allowed.
    func isBuiltIn(_ command: [String]) -> Bool {
        command.count >= 2 && Array(command.prefix(2)) == self.command
    }

    /// The model the helper will load: the command's `--model` when it is the
    /// built-in command, else what `saved_model()` in the helper picks
    /// (`$YTT_LLM_MODEL`, then `llm_model` in the ytt config file), else the default.
    func model(for command: [String], environment env: [String: String]) -> String {
        if isBuiltIn(command), let index = command.firstIndex(of: "--model"), index + 1 < command.count {
            return command[index + 1]
        }
        if let value = env["YTT_LLM_MODEL"], !value.isEmpty { return value }
        let configPath = env["YTT_CONFIG"].map { ($0 as NSString).expandingTildeInPath }
            ?? ((env["XDG_CONFIG_HOME"] ?? NSHomeDirectory() + "/.config") as NSString)
                .appendingPathComponent("ytt/config.json")
        if let data = FileManager.default.contents(atPath: configPath),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let value = object["llm_model"] as? String, !value.isEmpty {
            return value
        }
        return Self.defaultModel
    }

    /// Environment for `uv` and the private Python: keeps `uv`'s Pythons and
    /// cache inside `root`, and drops variables that would pull in another Python.
    func environment(base: [String: String] = TranscriptionRunner.processEnvironment()) -> [String: String] {
        var env = base
        for key in ["VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "UV_PYTHON"] {
            env.removeValue(forKey: key)
        }
        env["UV_PYTHON_INSTALL_DIR"] = root.appendingPathComponent("python").path
        env["UV_CACHE_DIR"] = root.appendingPathComponent("cache").path
        env["NO_COLOR"] = "1"
        return env
    }

    /// The Hugging Face cache folder for a model repo id.
    static func modelCacheFolder(_ model: String, environment env: [String: String]) -> URL {
        let hub = env["HF_HUB_CACHE"]
            ?? env["HF_HOME"].map { ($0 as NSString).appendingPathComponent("hub") }
            ?? NSHomeDirectory() + "/.cache/huggingface/hub"
        return URL(fileURLWithPath: hub, isDirectory: true)
            .appendingPathComponent("models--" + model.replacingOccurrences(of: "/", with: "--"), isDirectory: true)
    }

    /// Local model folders need no download.
    static func isLocalModel(_ model: String) -> Bool {
        model.hasPrefix("/") || model.hasPrefix("~") || model.hasPrefix(".")
    }

    /// Total size of the regular files under `folder`.
    static func directorySize(_ folder: URL) -> Int64 {
        let keys: Set<URLResourceKey> = [.fileSizeKey, .isRegularFileKey]
        guard let items = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: Array(keys)) else { return 0 }
        var total: Int64 = 0
        for case let url as URL in items {
            let values = try? url.resourceValues(forKeys: keys)
            if values?.isRegularFile == true { total += Int64(values?.fileSize ?? 0) }
        }
        return total
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Replaces the installed helper with `source`.
    func copyRunner(from source: URL) throws {
        let fm = FileManager.default
        let staged = root.appendingPathComponent(".runner.tmp")
        try? fm.removeItem(at: staged)
        try fm.copyItem(at: source, to: staged)
        if fm.fileExists(atPath: runner.path) { try fm.removeItem(at: runner) }
        try fm.moveItem(at: staged, to: runner)
    }

    /// Updates the installed helper from the app bundle, so app updates reach it.
    func refreshRunner() {
        guard isInstalled, let bundled = Self.bundledRunner else { return }
        try? copyRunner(from: bundled)
    }
}

enum EnhancementSetupError: LocalizedError {
    case unsupported
    case runnerMissing
    case downloadFailed(Int)
    case checksumMismatch
    case stepFailed(step: String, detail: String)

    var errorDescription: String? {
        switch self {
        case .unsupported:
            return "The built-in AI model needs a Mac with Apple silicon."
        case .runnerMissing:
            return "The rewrite helper is missing from the app. Rebuild the app and try again."
        case let .downloadFailed(status):
            return "Downloading the installer failed (HTTP \(status)). Check your internet connection and try again."
        case .checksumMismatch:
            return "The downloaded installer did not match its expected checksum, so it was not used."
        case let .stepFailed(step, detail):
            return detail.isEmpty ? "\(step) failed." : "\(step) failed:\n\(detail)"
        }
    }
}

/// Runs the one-click install of the built-in AI enhancement and reports progress.
@MainActor
@Observable
final class EnhancementInstaller {
    enum Phase: Equatable {
        case notInstalled
        case installing(step: String, detail: String)
        case installed
        case failed(String)
    }

    private(set) var phase: Phase
    let setup: EnhancementSetup
    private var task: Task<Void, Never>?

    init(setup: EnhancementSetup = .standard) {
        self.setup = setup
        phase = setup.isInstalled ? .installed : .notInstalled
    }

    var isInstalling: Bool {
        if case .installing = phase { return true }
        return false
    }

    /// Installs everything, downloads `model`, then calls `onSuccess`.
    func install(model: String, onSuccess: @escaping @MainActor () -> Void) {
        guard !isInstalling else { return }
        phase = .installing(step: "Starting", detail: "")
        task = Task {
            do {
                try await performInstall(model: model)
                phase = .installed
                onSuccess()
            } catch {
                if Task.isCancelled {
                    phase = setup.isInstalled ? .installed : .notInstalled
                } else {
                    phase = .failed(error.localizedDescription)
                }
            }
        }
    }

    func cancel() {
        task?.cancel()
        task = nil
    }

    /// Deletes the private Python, MLX-LM and helper. The downloaded model stays
    /// in the shared Hugging Face cache.
    func remove() throws {
        cancel()
        if FileManager.default.fileExists(atPath: setup.root.path) {
            try FileManager.default.removeItem(at: setup.root)
        }
        phase = .notInstalled
    }

    private func performInstall(model: String) async throws {
        guard EnhancementSetup.isSupported else { throw EnhancementSetupError.unsupported }
        guard let bundledRunner = EnhancementSetup.bundledRunner else { throw EnhancementSetupError.runnerMissing }
        let fm = FileManager.default
        try? fm.removeItem(at: setup.marker)
        try fm.createDirectory(at: setup.root, withIntermediateDirectories: true)
        let env = setup.environment()

        var step = "Downloading the installer"
        phase = .installing(step: step, detail: "uv \(EnhancementSetup.uvVersion)")
        let (download, response) = try await URLSession.shared.download(from: EnhancementSetup.uvURL)
        defer { try? fm.removeItem(at: download) }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw EnhancementSetupError.downloadFailed(http.statusCode)
        }
        // Never run a binary that does not match the pinned release.
        let archive = try Data(contentsOf: download, options: .mappedIfSafe)
        guard EnhancementSetup.sha256(archive) == EnhancementSetup.uvSHA256 else {
            throw EnhancementSetupError.checksumMismatch
        }
        let bin = setup.uv.deletingLastPathComponent()
        try? fm.removeItem(at: bin)
        try fm.createDirectory(at: bin, withIntermediateDirectories: true)
        try await run(step, URL(fileURLWithPath: "/usr/bin/tar"),
                      ["-xzf", download.path, "-C", bin.path, "--strip-components", "1"], env)

        step = "Installing Python \(EnhancementSetup.pythonVersion)"
        phase = .installing(step: step, detail: "A private copy, used only by this app")
        try? fm.removeItem(at: setup.venv)
        try await run(step, setup.uv, ["venv", "--no-config", "--managed-python",
                                       "--python", EnhancementSetup.pythonVersion, setup.venv.path], env)

        step = "Installing MLX-LM"
        phase = .installing(step: step, detail: EnhancementSetup.mlxLMRequirement)
        try await run(step, setup.uv, ["pip", "install", "--no-config",
                                       "--python", setup.python.path, EnhancementSetup.mlxLMRequirement], env)
        try await run(step, setup.python, ["-c", "import mlx_lm"], env)
        try setup.copyRunner(from: bundledRunner)

        if !EnhancementSetup.isLocalModel(model) {
            try await downloadModel(model, env: env)
        }

        let info = ["uv": EnhancementSetup.uvVersion, "python": EnhancementSetup.pythonVersion,
                    "mlx_lm": EnhancementSetup.mlxLMRequirement]
        try JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted, .sortedKeys])
            .write(to: setup.marker, options: .atomic)
    }

    /// Downloads the model ahead of the first enhancement, showing how much has arrived.
    private func downloadModel(_ model: String, env: [String: String]) async throws {
        let step = "Downloading the language model"
        let blobs = EnhancementSetup.modelCacheFolder(model, environment: env).appendingPathComponent("blobs")
        let name = model.replacingOccurrences(of: "mlx-community/", with: "")
        let poll = Task { [weak self] in
            while !Task.isCancelled {
                let bytes = EnhancementSetup.directorySize(blobs)
                let size = ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
                self?.phase = .installing(step: step, detail: "\(name) · \(size) so far")
                try? await Task.sleep(for: .seconds(1))
            }
        }
        defer { poll.cancel() }
        try await run(step, setup.python, [
            "-c", "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1])", model,
        ], env)
    }

    private func run(_ step: String, _ executable: URL, _ arguments: [String], _ env: [String: String]) async throws {
        let result = try await TranscriptionRunner.execute(executable: executable, arguments: arguments, environment: env)
        try Task.checkCancellation()
        guard result.status == 0 else {
            let tail = result.stderr.split(whereSeparator: \.isNewline).suffix(6).joined(separator: "\n")
            throw EnhancementSetupError.stepFailed(step: step, detail: tail)
        }
    }
}

// [AI-GENERATED] Claude Code agent; pending human review.
import CryptoKit
import Foundation

/// Optional parts of the on-device AI runtime.
enum AIComponent: String, CaseIterable, Codable, Identifiable {
    /// MLX-LM, which cleans up transcripts ("Enhance").
    case enhancement
    /// MLX Whisper speech recognition. Pulls in PyTorch, so it is opt-in.
    case speech

    var id: String { rawValue }
}

/// Where the app's private AI runtime lives, and what the app bundle ships
/// to build it (see `scripts/bundle-ai-runtime.sh`).
///
/// Nothing here touches the user's own Python, pipx or Homebrew setup: Python,
/// the virtual environment and uv's cache all stay inside `root` and `cache`.
struct AIRuntimeLayout: Equatable {
    /// `~/Library/Application Support/YTTranscribe/AIRuntime`.
    var root: URL
    /// uv's download cache, `~/Library/Caches/com.maugx3.yttranscribe/uv`.
    var cache: URL
    /// The bundled uv binary, if this build has one.
    var uv: URL?
    /// The bundled locks and helper scripts, if this build has them.
    var resources: URL?

    var venv: URL { root.appendingPathComponent("venv", isDirectory: true) }
    /// The next environment is built here, then moved over `venv`, so a failed
    /// or cancelled install never breaks a working one.
    var staging: URL { root.appendingPathComponent("venv.new", isDirectory: true) }
    var binDirectory: URL { venv.appendingPathComponent("bin", isDirectory: true) }
    var python: URL { binDirectory.appendingPathComponent("python") }
    var pythonInstalls: URL { root.appendingPathComponent("python", isDirectory: true) }
    var manifestURL: URL { root.appendingPathComponent("manifest.json") }

    var runner: URL? { resources?.appendingPathComponent("rewrite_with_local_model.py") }
    var modelFetcher: URL? { resources?.appendingPathComponent("fetch_mlx_model.py") }

    /// The lock to install. Speech's lock also contains everything Enhance needs.
    func lockFile(for components: Set<AIComponent>) -> URL? {
        let name = components.contains(.speech) ? "requirements-speech" : "requirements-enhance"
        return resources?.appendingPathComponent("\(name).txt")
    }

    /// Whether this build can install the runtime.
    var canInstall: Bool {
        let fm = FileManager.default
        guard let uv, let lock = lockFile(for: [.enhancement]) else { return false }
        return fm.isExecutableFile(atPath: uv.path) && fm.fileExists(atPath: lock.path)
    }

    static var standard: AIRuntimeLayout {
        let fm = FileManager.default
        let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? fm.temporaryDirectory
        let caches = fm.urls(for: .cachesDirectory, in: .userDomainMask).first ?? fm.temporaryDirectory
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/uv")
        return AIRuntimeLayout(
            root: support.appendingPathComponent("YTTranscribe/AIRuntime", isDirectory: true),
            cache: caches.appendingPathComponent("com.maugx3.yttranscribe/uv", isDirectory: true),
            uv: fm.fileExists(atPath: helper.path) ? helper : nil,
            resources: Bundle.main.resourceURL?.appendingPathComponent("AIRuntime", isDirectory: true)
        )
    }
}

/// Written after a successful install; says what is installed and from which lock.
struct AIRuntimeManifest: Codable, Equatable {
    var lockDigest: String
    var components: [AIComponent]
    var installedAt: Date
    var uvVersion: String
}

enum AIRuntimeStatus: Equatable {
    /// This build has no bundled uv, so it cannot set the runtime up.
    case unavailable
    case notInstalled
    /// Installed and usable. `outdated` when the app now ships a newer lock.
    case ready(components: Set<AIComponent>, outdated: Bool)
    /// Files are there but the environment is incomplete (for example an
    /// interrupted install, or the Python it points to was deleted).
    case damaged

    var isReady: Bool {
        if case .ready = self { return true }
        return false
    }

    var components: Set<AIComponent> {
        if case let .ready(components, _) = self { return components }
        return []
    }
}

/// One command of the install, shown as a step in the progress UI.
struct AIRuntimeStep: Equatable {
    let title: String
    let executable: URL
    let arguments: [String]
}

enum AIRuntime {
    static let uvVersion = "0.13.9"
    static let pythonVersion = "3.12"
    /// Same default as `tools/rewrite_with_local_model.py`.
    static let defaultLLM = "mlx-community/Qwen2.5-3B-Instruct-4bit"

    static func status(layout: AIRuntimeLayout, fileManager fm: FileManager = .default) -> AIRuntimeStatus {
        let manifest = readManifest(layout: layout)
        // The venv's python is a symlink into `pythonInstalls`; the check
        // follows it, so a deleted interpreter counts as missing.
        let pythonWorks = fm.isExecutableFile(atPath: layout.python.path)
        if let manifest, pythonWorks {
            let components = Set(manifest.components)
            let current = layout.lockFile(for: components).flatMap(digest(of:))
            return .ready(components: components, outdated: current != nil && current != manifest.lockDigest)
        }
        if manifest != nil || fm.fileExists(atPath: layout.venv.path) {
            return .damaged
        }
        return layout.canInstall ? .notInstalled : .unavailable
    }

    static func readManifest(layout: AIRuntimeLayout) -> AIRuntimeManifest? {
        guard let data = try? Data(contentsOf: layout.manifestURL) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(AIRuntimeManifest.self, from: data)
    }

    static func writeManifest(_ manifest: AIRuntimeManifest, layout: AIRuntimeLayout) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(manifest).write(to: layout.manifestURL, options: .atomic)
    }

    /// SHA-256 of a file, as lowercase hex.
    static func digest(of url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// The rewrite command Enhance uses when no custom command is set: the
    /// runtime's Python running the bundled MLX-LM runner.
    static func managedRewriteCommand(layout: AIRuntimeLayout, model: String?, status: AIRuntimeStatus? = nil) -> [String]? {
        let current = status ?? Self.status(layout: layout)
        guard current.components.contains(.enhancement), let runner = layout.runner,
              FileManager.default.fileExists(atPath: runner.path) else { return nil }
        // -I: ignore PYTHONPATH and user site-packages from the user's shell setup.
        var command = [layout.python.path, "-I", runner.path]
        if let model, !model.isEmpty { command += ["--model", model] }
        return command
    }

    /// Environment for uv and the runtime's Python. Keeps uv's Python
    /// downloads and cache inside the app's folders, ignores the user's uv
    /// config files, and drops variables that would point Python elsewhere.
    static func environment(layout: AIRuntimeLayout, base: [String: String]) -> [String: String] {
        var env = base
        for key in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON"] {
            env.removeValue(forKey: key)
        }
        env["UV_PYTHON_INSTALL_DIR"] = layout.pythonInstalls.path
        env["UV_CACHE_DIR"] = layout.cache.path
        env["UV_NO_CONFIG"] = "1"
        // Use the macOS keychain's certificates, so networks with their own
        // TLS root (company proxies) work like they do in Safari.
        env["UV_SYSTEM_CERTS"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        return env
    }

    /// The commands that build the environment in `layout.staging`. The caller
    /// moves it into place and writes the manifest once they all succeed.
    static func installSteps(layout: AIRuntimeLayout, components: Set<AIComponent>) -> [AIRuntimeStep]? {
        guard let uv = layout.uv, let lock = layout.lockFile(for: components) else { return nil }
        let stagingPython = layout.staging.appendingPathComponent("bin/python")
        var check = "import mlx.core as mx, mlx_lm; mx.eval(mx.array([1, 2]).sum())"
        if components.contains(.speech) { check += "; import mlx_whisper" }
        return [
            AIRuntimeStep(
                title: "Downloading Python \(pythonVersion)",
                executable: uv,
                // --no-bin: do not add python3.12 to ~/.local/bin.
                arguments: ["python", "install", pythonVersion, "--no-bin", "--no-config"]
            ),
            AIRuntimeStep(
                title: "Creating the environment",
                executable: uv,
                arguments: [
                    "venv", layout.staging.path, "--python", pythonVersion, "--managed-python",
                    "--no-python-downloads", "--relocatable", "--clear", "--no-config",
                ]
            ),
            AIRuntimeStep(
                title: components.contains(.speech) ? "Installing MLX, MLX-LM and MLX Whisper" : "Installing MLX and MLX-LM",
                executable: uv,
                // Exact versions, every file checked against the lock's
                // SHA-256 hashes, and no building from source.
                arguments: [
                    "pip", "sync", lock.path, "--python", stagingPython.path,
                    "--require-hashes", "--only-binary", ":all:", "--no-config",
                ]
            ),
            AIRuntimeStep(
                title: "Checking that MLX runs on this Mac",
                executable: stagingPython,
                arguments: ["-I", "-c", check]
            ),
        ]
    }

    /// Pre-downloads a model into the Hugging Face cache, printing JSON progress.
    static func modelDownloadStep(layout: AIRuntimeLayout, model: String) -> AIRuntimeStep? {
        guard let fetcher = layout.modelFetcher else { return nil }
        return AIRuntimeStep(title: "Downloading the language model", executable: layout.python, arguments: ["-I", fetcher.path, model])
    }

    /// Moves the freshly built environment over the old one.
    static func promoteStaging(layout: AIRuntimeLayout, fileManager fm: FileManager = .default) throws {
        let old = layout.root.appendingPathComponent("venv.old", isDirectory: true)
        try? fm.removeItem(at: old)
        if fm.fileExists(atPath: layout.venv.path) {
            try fm.moveItem(at: layout.venv, to: old)
        }
        do {
            try fm.moveItem(at: layout.staging, to: layout.venv)
        } catch {
            // Put the previous environment back so the app keeps working.
            if fm.fileExists(atPath: old.path) { try? fm.moveItem(at: old, to: layout.venv) }
            throw error
        }
        try? fm.removeItem(at: old)
    }

    /// Fraction done from a `fetch_mlx_model.py` progress line, if it is one.
    static func downloadFraction(fromLine line: String) -> Double? {
        guard line.hasPrefix("{"),
              let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
              object["event"] as? String == "progress",
              let done = (object["done"] as? NSNumber)?.doubleValue,
              let total = (object["total"] as? NSNumber)?.doubleValue, total > 0 else { return nil }
        return min(1, max(0, done / total))
    }
}

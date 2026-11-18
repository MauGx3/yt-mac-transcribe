import Foundation

/// Report printed by `ytt demo --json`: timings, accuracy and a recommended
/// model for speech to text and for LLM cleanup on this Mac.
struct BenchmarkReport: Decodable, Equatable {
    struct System: Decodable, Equatable {
        var chip: String?
        var ramGb: Int?
        var osVersion: String?
        var appleSilicon: Bool?
    }

    struct Sample: Decodable, Equatable {
        var source: String
        var words: Int
        var durationS: Double
    }

    struct ASRResult: Decodable, Equatable, Identifiable {
        var engine: String
        var model: String
        var status: String
        var reason: String?
        var seconds: Double?
        var realtimeX: Double?
        var wer: Double?

        var id: String { engine + "/" + model }
        var isMeasured: Bool { status == "ok" }
    }

    struct LLMResult: Decodable, Equatable, Identifiable {
        var model: String
        var status: String
        var reason: String?
        var note: String?
        var seconds: Double?
        var wer: Double?
        var strict: Double?
        var sizeGb: Double?

        var id: String { model }
        var isMeasured: Bool { status == "ok" }
        /// Repo name without the `mlx-community/` prefix.
        var shortName: String { model.replacingOccurrences(of: "mlx-community/", with: "") }
    }

    struct Recommendation: Decodable, Equatable {
        struct ASR: Decodable, Equatable {
            var engine: String
            var model: String
            var measured: Bool
            var reason: String
        }

        struct LLM: Decodable, Equatable {
            var model: String
            var measured: Bool
            var reason: String
        }

        var asr: ASR
        var llm: LLM
    }

    var system: System
    var sample: Sample
    var asr: [ASRResult]
    var llm: [LLMResult]
    var recommendation: Recommendation
    var asrError: String?
    var llmNote: String?

    static func decode(_ data: Data) throws -> BenchmarkReport {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(BenchmarkReport.self, from: data)
    }

    static func percent(_ value: Double?) -> String {
        guard let value else { return "–" }
        return String(format: "%.1f%%", value * 100)
    }

    static func seconds(_ value: Double?) -> String {
        guard let value else { return "–" }
        return String(format: "%.1f s", value)
    }

    static func speed(_ value: Double?) -> String {
        guard let value else { return "–" }
        return String(format: "%.1f×", value)
    }
}

enum BenchmarkRunner {
    /// `ytt demo` arguments. The LLM part needs the rewrite command from
    /// Settings, so without one only speech to text is measured.
    static func arguments(settings: AppSettings, download: Bool) -> [String] {
        var args = ["demo", "--json", "--no-pick", "--quiet"]
        if download { args.append("--download") }
        if settings.rewriteCommand.isEmpty {
            args.append("--asr-only")
        } else {
            // `--runner` takes the rest of the line, so it goes last.
            args += ["--runner"] + settings.rewriteCommand
        }
        return args
    }

    static func run(settings: AppSettings, download: Bool) async throws -> BenchmarkReport {
        let result = try await TranscriptionRunner.execute(
            executable: settings.yttExecutable,
            arguments: arguments(settings: settings, download: download)
        )
        try Task.checkCancellation()
        guard result.status == 0 else {
            throw TranscriptionRunnerError.commandFailed(
                status: result.status,
                detail: result.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        }
        return try BenchmarkReport.decode(Data(result.stdout.utf8))
    }
}

extension AppSettings {
    /// The rewrite command with its `--model` argument set to `model`.
    static func rewriteCommand(_ command: [String], settingModel model: String) -> [String] {
        var tokens = command
        if let index = tokens.firstIndex(of: "--model") {
            if index + 1 < tokens.count {
                tokens[index + 1] = model
            } else {
                tokens.append(model)
            }
        } else if let index = tokens.firstIndex(where: { $0.hasPrefix("--model=") }) {
            tokens[index] = "--model=" + model
        } else {
            tokens += ["--model", model]
        }
        return tokens
    }
}

extension TranscriptionViewModel {
    /// Applies models picked on the Benchmark tab and remembers them.
    func applyBenchmarkChoice(engine: String? = nil, model: String? = nil, llmModel: String? = nil, defaults: UserDefaults = .standard) {
        var updated = settings
        if let engine, let parsed = ASREngine(rawValue: engine) { updated.engine = parsed }
        if let model { updated.model = model }
        if let llmModel, !updated.rewriteCommand.isEmpty {
            updated.rewriteCommand = AppSettings.rewriteCommand(updated.rewriteCommand, settingModel: llmModel)
        }
        updated.persist(to: defaults)
        updateSettings(updated)
    }
}

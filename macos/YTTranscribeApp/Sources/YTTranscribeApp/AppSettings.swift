import Foundation

/// Local speech-recognition engine used when a video has no usable captions.
enum ASREngine: String, CaseIterable, Identifiable {
    case auto
    case whisperCpp = "whisper-cpp"
    case mlx

    var id: String { rawValue }

    var label: String {
        switch self {
        case .auto: return "Automatic"
        case .whisperCpp: return "whisper.cpp"
        case .mlx: return "MLX Whisper (Apple Silicon)"
        }
    }
}

/// Short model names understood by `ytt --model` for both engines.
enum ASRModel {
    static let defaultName = "small.en"
    static let names = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3", "large-v3-turbo"]
}

struct AppSettings: Equatable {
    var yttExecutable: URL
    var rewriteCommand: [String]
    var outputDirectory: URL
    var formats: [OutputFormat] = [.txt]
    var engine: ASREngine = .auto
    var model: String = ASRModel.defaultName
    /// Language model for the built-in Enhance command; nil uses the runner's default.
    var llmModel: String? = nil
    /// The built-in Enhance command (on-device AI runtime), when it is installed.
    var managedRewriteCommand: [String] = []

    /// The command Enhance runs: the custom one from Settings, otherwise the
    /// built-in on-device AI. Empty when neither is available.
    var effectiveRewriteCommand: [String] {
        rewriteCommand.isEmpty ? managedRewriteCommand : rewriteCommand
    }

    /// Selected formats, deduplicated; never empty.
    var effectiveFormats: [OutputFormat] { OutputFormat.normalized(formats) }

    static let defaultOutputDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Documents/yt-transcribe", isDirectory: true)

    static var defaults: AppSettings {
        load(from: .standard, environment: ProcessInfo.processInfo.environment)
    }

    /// The `ytt` CLI packaged inside the app bundle by `scripts/bundle-ytt.sh`.
    static var bundledExecutable: URL? {
        Bundle.main.url(forResource: "ytt", withExtension: "pyz")
    }

    /// `runtime == nil` skips looking for the on-device AI runtime (tests).
    static func load(from values: UserDefaults, environment env: [String: String], runtime: AIRuntimeLayout? = AIRuntimeLayout.standard) -> AppSettings {
        let rewrite = values.string(forKey: "rewriteCommand") ?? env["YTT_REWRITE_COMMAND"] ?? ""
        let defaultExecutable = bundledExecutable?.path ?? "/opt/homebrew/bin/ytt"
        let llmModel = values.string(forKey: "llmModel").flatMap { $0.isEmpty ? nil : $0 }
        var settings = AppSettings(
            yttExecutable: URL(fileURLWithPath: values.string(forKey: "yttExecutable") ?? env["YTT_EXECUTABLE"] ?? defaultExecutable),
            rewriteCommand: Self.parseCommand(rewrite) ?? [],
            outputDirectory: URL(fileURLWithPath: values.string(forKey: "outputDirectory") ?? defaultOutputDirectory.path, isDirectory: true),
            formats: OutputFormat.parse(values.string(forKey: "formats") ?? "txt"),
            engine: values.string(forKey: "asrEngine").flatMap(ASREngine.init(rawValue:)) ?? .auto,
            model: values.string(forKey: "asrModel").flatMap { $0.isEmpty ? nil : $0 } ?? ASRModel.defaultName
        )
        settings.llmModel = llmModel
        if let runtime {
            settings.managedRewriteCommand = AIRuntime.managedRewriteCommand(layout: runtime, model: llmModel) ?? []
        }
        return settings
    }

    static func parseCommand(_ command: String) -> [String]? {
        var tokens: [String] = []
        var token = ""
        var quote: Character?
        var escaping = false
        var tokenStarted = false

        for character in command {
            if escaping {
                token.append(character)
                escaping = false
                tokenStarted = true
            } else if character == "\\", quote != "'" {
                escaping = true
                tokenStarted = true
            } else if let activeQuote = quote {
                if character == activeQuote {
                    quote = nil
                } else {
                    token.append(character)
                }
                tokenStarted = true
            } else if character == "\"" || character == "'" {
                quote = character
                tokenStarted = true
            } else if character.isWhitespace {
                if tokenStarted {
                    tokens.append(token)
                    token = ""
                    tokenStarted = false
                }
            } else {
                token.append(character)
                tokenStarted = true
            }
        }

        guard !escaping, quote == nil else { return nil }
        if tokenStarted { tokens.append(token) }
        guard tokens.first.map({ !$0.isEmpty }) ?? true else { return nil }
        return tokens
    }

    func persist(to defaults: UserDefaults = .standard) {
        // The bundled copy moves with the app, so its path is never saved.
        if yttExecutable.path == Self.bundledExecutable?.path {
            defaults.removeObject(forKey: "yttExecutable")
        } else {
            defaults.set(yttExecutable.path, forKey: "yttExecutable")
        }
        defaults.set(rewriteCommand.joined(separator: " "), forKey: "rewriteCommand")
        defaults.set(outputDirectory.path, forKey: "outputDirectory")
        defaults.set(effectiveFormats.map(\.rawValue).joined(separator: ","), forKey: "formats")
        defaults.set(engine.rawValue, forKey: "asrEngine")
        defaults.set(model, forKey: "asrModel")
        if let llmModel { defaults.set(llmModel, forKey: "llmModel") } else { defaults.removeObject(forKey: "llmModel") }
    }
}

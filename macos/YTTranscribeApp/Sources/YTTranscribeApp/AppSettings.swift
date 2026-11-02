import Foundation

struct AppSettings: Equatable {
    var yttExecutable: URL
    var rewriteCommand: [String]
    var outputDirectory: URL

    static let defaultOutputDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Documents/yt-transcribe", isDirectory: true)

    static var defaults: AppSettings {
        load(from: .standard, environment: ProcessInfo.processInfo.environment)
    }

    static func load(from values: UserDefaults, environment env: [String: String]) -> AppSettings {
        let rewrite = values.string(forKey: "rewriteCommand") ?? env["YTT_REWRITE_COMMAND"] ?? ""
        return AppSettings(
            yttExecutable: URL(fileURLWithPath: values.string(forKey: "yttExecutable") ?? env["YTT_EXECUTABLE"] ?? "/opt/homebrew/bin/ytt"),
            rewriteCommand: Self.parseCommand(rewrite) ?? [],
            outputDirectory: URL(fileURLWithPath: values.string(forKey: "outputDirectory") ?? defaultOutputDirectory.path, isDirectory: true)
        )
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
        return tokens
    }

    func persist(to defaults: UserDefaults = .standard) {
        defaults.set(yttExecutable.path, forKey: "yttExecutable")
        defaults.set(rewriteCommand.joined(separator: " "), forKey: "rewriteCommand")
        defaults.set(outputDirectory.path, forKey: "outputDirectory")
    }
}

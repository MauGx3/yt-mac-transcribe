import Foundation

enum TranscriptionMode {
    case transcribe
    case review
}

struct TranscriptFiles: Equatable {
    let original: URL
    var reviewed: URL?
}

enum TranscriptionRunnerError: LocalizedError {
    case rewriteCommandMissing
    case commandFailed(status: Int32, detail: String)
    case missingOutput
    case cancelled

    var errorDescription: String? {
        switch self {
        case .rewriteCommandMissing:
            return "Configure a local rewrite command in Settings before requesting a reviewed transcript."
        case let .commandFailed(status, detail):
            return detail.isEmpty ? "ytt exited with status \(status)." : detail
        case .missingOutput:
            return "ytt finished successfully but did not report the expected transcript output."
        case .cancelled:
            return "Transcription was cancelled."
        }
    }
}

protocol TranscriptionRunning {
    func transcribe(url: String, settings: AppSettings) async throws -> TranscriptFiles
    func review(url: String, settings: AppSettings) async throws -> TranscriptFiles
}

struct TranscriptionRunner: TranscriptionRunning {
    static func files(from paths: [URL], mode: TranscriptionMode) throws -> TranscriptFiles {
        guard let original = paths.first else { throw TranscriptionRunnerError.missingOutput }
        let reviewed: URL?
        if case .review = mode {
            guard paths.count > 1 else { throw TranscriptionRunnerError.missingOutput }
            reviewed = paths[1]
        } else {
            reviewed = nil
        }
        return TranscriptFiles(original: original, reviewed: reviewed)
    }

    static func arguments(for mode: TranscriptionMode, url: String, settings: AppSettings) -> [String] {
        var args = [url, "-f", "txt", "-o", settings.outputDirectory.path]
        if case .review = mode {
            args += ["--rewrite-command"] + settings.rewriteCommand
        }
        return args
    }

    func transcribe(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        let output = try await run(.transcribe, url: url, settings: settings)
        return TranscriptFiles(original: output.original, reviewed: nil)
    }

    func review(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        guard !settings.rewriteCommand.isEmpty else {
            throw TranscriptionRunnerError.rewriteCommandMissing
        }
        let output = try await run(.review, url: url, settings: settings)
        guard let reviewed = output.reviewed else {
            throw TranscriptionRunnerError.missingOutput
        }
        return TranscriptFiles(original: output.original, reviewed: reviewed)
    }

    private func run(_ mode: TranscriptionMode, url: String, settings: AppSettings) async throws -> TranscriptFiles {
        try FileManager.default.createDirectory(at: settings.outputDirectory, withIntermediateDirectories: true)
        let result = try await Self.execute(
            executable: settings.yttExecutable,
            arguments: Self.arguments(for: mode, url: url, settings: settings)
        )
        guard result.status == 0 else {
            throw TranscriptionRunnerError.commandFailed(status: result.status, detail: result.stderr.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let paths = result.stdout
            .split(whereSeparator: \.isNewline)
            .map { URL(fileURLWithPath: String($0).trimmingCharacters(in: .whitespacesAndNewlines)) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
        return try Self.files(from: paths, mode: mode)
    }

    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    private static func execute(executable: URL, arguments: [String]) async throws -> ProcessResult {
        let process = Process()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                let outPipe = Pipe()
                let errPipe = Pipe()
                process.executableURL = executable
                process.arguments = arguments
                process.standardOutput = outPipe
                process.standardError = errPipe
                process.terminationHandler = { terminated in
                    let out = outPipe.fileHandleForReading.readDataToEndOfFile()
                    let err = errPipe.fileHandleForReading.readDataToEndOfFile()
                    continuation.resume(returning: ProcessResult(
                        status: terminated.terminationStatus,
                        stdout: String(decoding: out, as: UTF8.self),
                        stderr: String(decoding: err, as: UTF8.self)
                    ))
                }
                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: {
            if process.isRunning { process.terminate() }
        })
    }
}

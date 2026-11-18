import Foundation

enum TranscriptionMode {
    case transcribe
    case review
}

struct TranscriptFiles: Equatable {
    let original: URL
    var reviewed: URL?
    /// Originals in the other requested formats.
    var extras: [URL] = []
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
    /// Batch or playlist run. Returns one entry per video that produced output.
    func transcribeMany(urls: [String], playlist: Bool, settings: AppSettings) async throws -> [TranscriptFiles]
}

struct TranscriptionRunner: TranscriptionRunning {
    private final class ProcessCancellationState: @unchecked Sendable {
        private let lock = NSLock()
        private var process: Process?
        private var cancelled = false

        func register(process: Process) -> Bool {
            lock.lock()
            defer { lock.unlock() }
            self.process = process
            return !cancelled
        }

        func cancel() -> Process? {
            lock.lock()
            defer { lock.unlock() }
            cancelled = true
            return process
        }

        var isCancelled: Bool {
            lock.lock()
            defer { lock.unlock() }
            return cancelled
        }
    }

    /// `ytt` prints every original (one per format) and then, with a rewrite
    /// command, every reviewed copy. `formatCount` splits the two groups.
    static func files(from paths: [URL], mode: TranscriptionMode, formatCount: Int = 1) throws -> TranscriptFiles {
        guard let original = paths.first else { throw TranscriptionRunnerError.missingOutput }
        let count = max(1, formatCount)
        let extras = Array(paths.dropFirst().prefix(count - 1))
        let reviewed: URL?
        if case .review = mode {
            guard paths.count > count else { throw TranscriptionRunnerError.missingOutput }
            reviewed = paths[count]
        } else {
            reviewed = nil
        }
        return TranscriptFiles(original: original, reviewed: reviewed, extras: extras)
    }

    /// Batch and playlist runs print `formatCount` paths per successful video.
    static func groups(from paths: [URL], formatCount: Int) -> [TranscriptFiles] {
        let count = max(1, formatCount)
        return stride(from: 0, to: paths.count, by: count).map { start in
            let chunk = Array(paths[start..<min(start + count, paths.count)])
            return TranscriptFiles(original: chunk[0], extras: Array(chunk.dropFirst()))
        }
    }

    static func arguments(for mode: TranscriptionMode, url: String, settings: AppSettings) -> [String] {
        var args = [url, "-f"] + settings.effectiveFormats.map(\.rawValue)
            + ["-o", settings.outputDirectory.path] + asrArguments(settings)
        if case .review = mode {
            args += ["--rewrite-command"] + settings.rewriteCommand
        }
        return args
    }

    /// Reviewed copies are not produced for batch runs, so no rewrite flags.
    /// `ytt` exit code for a batch or playlist where some videos failed.
    static let partialFailureStatus: Int32 = 3

    static func batchArguments(urls: [String], playlist: Bool, settings: AppSettings) -> [String] {
        (playlist ? ["--playlist"] : []) + urls
            + ["-f"] + settings.effectiveFormats.map(\.rawValue) + ["-o", settings.outputDirectory.path]
            + asrArguments(settings)
    }

    /// Speech engine and model, used when a video has no usable captions.
    static func asrArguments(_ settings: AppSettings) -> [String] {
        ["--engine", settings.engine.rawValue, "--model", settings.model]
    }

    func transcribe(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        try await run(.transcribe, url: url, settings: settings)
    }

    func review(url: String, settings: AppSettings) async throws -> TranscriptFiles {
        guard !settings.rewriteCommand.isEmpty else {
            throw TranscriptionRunnerError.rewriteCommandMissing
        }
        let output = try await run(.review, url: url, settings: settings)
        guard let reviewed = output.reviewed else {
            throw TranscriptionRunnerError.missingOutput
        }
        return TranscriptFiles(original: output.original, reviewed: reviewed, extras: output.extras)
    }

    func transcribeMany(urls: [String], playlist: Bool, settings: AppSettings) async throws -> [TranscriptFiles] {
        guard !urls.isEmpty else { throw TranscriptionRunnerError.missingOutput }
        // A batch where only some videos failed still wrote the others, so
        // keep them; the summary shows how many of the requested URLs worked.
        let paths = try await outputPaths(
            arguments: Self.batchArguments(urls: urls, playlist: playlist, settings: settings),
            settings: settings,
            acceptedStatuses: [0, Self.partialFailureStatus]
        )
        let groups = Self.groups(from: paths, formatCount: settings.effectiveFormats.count)
        guard !groups.isEmpty else { throw TranscriptionRunnerError.missingOutput }
        return groups
    }

    private func run(_ mode: TranscriptionMode, url: String, settings: AppSettings) async throws -> TranscriptFiles {
        let paths = try await outputPaths(arguments: Self.arguments(for: mode, url: url, settings: settings), settings: settings)
        return try Self.files(from: paths, mode: mode, formatCount: settings.effectiveFormats.count)
    }

    /// Runs `ytt` and returns the existing files it printed on stdout.
    private func outputPaths(arguments: [String], settings: AppSettings, acceptedStatuses: Set<Int32> = [0]) async throws -> [URL] {
        try FileManager.default.createDirectory(at: settings.outputDirectory, withIntermediateDirectories: true)
        let result: ProcessResult
        do {
            result = try await Self.execute(executable: settings.yttExecutable, arguments: arguments)
            try Task.checkCancellation()
        } catch is CancellationError {
            throw TranscriptionRunnerError.cancelled
        }
        guard acceptedStatuses.contains(result.status) else {
            throw TranscriptionRunnerError.commandFailed(status: result.status, detail: result.stderr.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return result.stdout
            .split(whereSeparator: \.isNewline)
            .map { URL(fileURLWithPath: String($0).trimmingCharacters(in: .whitespacesAndNewlines)) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
    }

    /// Drains a pipe on a background queue while the child runs.
    ///
    /// Reading only after exit deadlocks once the child fills the pipe
    /// buffer (~64 KB): it blocks on write and never terminates.
    private final class PipeDrain: @unchecked Sendable {
        private let lock = NSLock()
        private var data = Data()
        private let finished = DispatchSemaphore(value: 0)

        init(_ pipe: Pipe) {
            let handle = pipe.fileHandleForReading
            DispatchQueue.global(qos: .utility).async { [self] in
                let chunk = handle.readDataToEndOfFile()
                lock.lock()
                data = chunk
                lock.unlock()
                finished.signal()
            }
        }

        /// Blocks until the pipe reaches EOF, then returns everything read.
        func collected() -> Data {
            finished.wait()
            lock.lock()
            defer { lock.unlock() }
            return data
        }
    }

    struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    // [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review.
    // GUI apps inherit a minimal PATH, but `ytt` looks up `yt-dlp` (and the
    // optional ASR tools) on PATH, so Homebrew locations are prepended here.
    static func processEnvironment(base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        let toolDirectories = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        var env = base
        let existing = (base["PATH"] ?? "").split(separator: ":").map(String.init)
        env["PATH"] = (toolDirectories + existing.filter { !toolDirectories.contains($0) }).joined(separator: ":")
        return env
    }

    /// Lets the drain threads hit EOF when the process never launched.
    private static func closeWriters(_ pipes: Pipe...) {
        for pipe in pipes { try? pipe.fileHandleForWriting.close() }
    }

    static func execute(executable: URL, arguments: [String]) async throws -> ProcessResult {
        let cancellationState = ProcessCancellationState()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                let process = Process()
                let outPipe = Pipe()
                let errPipe = Pipe()
                // Drain from before launch so the termination handler can
                // never run ahead of the readers.
                let outDrain = PipeDrain(outPipe)
                let errDrain = PipeDrain(errPipe)
                process.executableURL = executable
                process.arguments = arguments
                process.environment = Self.processEnvironment()
                process.standardOutput = outPipe
                process.standardError = errPipe
                process.terminationHandler = { terminated in
                    if cancellationState.isCancelled {
                        continuation.resume(throwing: CancellationError())
                        return
                    }
                    let out = outDrain.collected()
                    let err = errDrain.collected()
                    continuation.resume(returning: ProcessResult(
                        status: terminated.terminationStatus,
                        stdout: String(decoding: out, as: UTF8.self),
                        stderr: String(decoding: err, as: UTF8.self)
                    ))
                }
                guard cancellationState.register(process: process), !Task.isCancelled else {
                    Self.closeWriters(outPipe, errPipe)
                    continuation.resume(throwing: CancellationError())
                    return
                }
                do {
                    try process.run()
                    if cancellationState.isCancelled, process.isRunning {
                        process.terminate()
                    }
                } catch {
                    Self.closeWriters(outPipe, errPipe)
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: {
            guard let process = cancellationState.cancel() else { return }
            if process.isRunning { process.terminate() }
        })
    }
}

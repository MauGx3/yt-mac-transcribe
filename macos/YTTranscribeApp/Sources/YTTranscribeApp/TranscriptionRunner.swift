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
    /// `<name>.review.json`, the diff of original vs enhanced text.
    var review: URL? = nil
}

enum TranscriptionRunnerError: LocalizedError {
    case rewriteCommandMissing
    case commandFailed(status: Int32, detail: String)
    case missingOutput
    case cancelled

    var errorDescription: String? {
        switch self {
        case .rewriteCommandMissing:
            return "Configure a local rewrite command in Settings before requesting an enhanced transcript."
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
    /// Review of a transcript already on disk. Rewrites its saved `.json`
    /// copy when there is one instead of fetching the video again.
    func review(files: TranscriptFiles, url: String, settings: AppSettings) async throws -> TranscriptFiles
    /// Receives each progress line `ytt` prints while it runs.
    func setProgressHandler(_ handler: (@Sendable (String) -> Void)?)
}

extension TranscriptionRunning {
    func review(files: TranscriptFiles, url: String, settings: AppSettings) async throws -> TranscriptFiles {
        try await review(url: url, settings: settings)
    }

    func setProgressHandler(_ handler: (@Sendable (String) -> Void)?) {}
}

/// Holds the progress callback for a value-type runner.
final class ProgressRelay: @unchecked Sendable {
    private let lock = NSLock()
    private var handler: (@Sendable (String) -> Void)?

    func set(_ handler: (@Sendable (String) -> Void)?) {
        lock.lock()
        self.handler = handler
        lock.unlock()
    }

    func send(_ line: String) {
        lock.lock()
        let handler = self.handler
        lock.unlock()
        handler?(line)
    }
}

struct TranscriptionRunner: TranscriptionRunning {
    private let progress = ProgressRelay()

    func setProgressHandler(_ handler: (@Sendable (String) -> Void)?) {
        progress.set(handler)
    }

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
        var review: URL?
        if case .review = mode {
            guard paths.count > count else { throw TranscriptionRunnerError.missingOutput }
            reviewed = paths[count]
            // Printed last, after every enhanced copy; older ytt builds omit it.
            review = paths.dropFirst(count + 1).first { $0.lastPathComponent.hasSuffix(".review.json") }
        } else {
            reviewed = nil
        }
        return TranscriptFiles(original: original, reviewed: reviewed, extras: extras, review: review)
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

    /// The saved `ytt -f json` copy of a transcript, if the user asked for one.
    static func savedTranscriptJSON(_ files: TranscriptFiles) -> URL? {
        ([files.original] + files.extras).first {
            $0.pathExtension.lowercased() == "json" && !$0.lastPathComponent.hasSuffix(".review.json")
                && FileManager.default.fileExists(atPath: $0.path)
        }
    }

    /// Rewrites a saved transcript with no network or speech recognition.
    /// `ytt` prints the same paths, in the same order, as a full review run.
    static func rewriteFromArguments(json: URL, settings: AppSettings) -> [String] {
        ["--rewrite-from", json.path, "-f"] + settings.effectiveFormats.map(\.rawValue)
            + ["-o", json.deletingLastPathComponent().path, "--rewrite-command"] + settings.rewriteCommand
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
        return TranscriptFiles(original: output.original, reviewed: reviewed, extras: output.extras, review: output.review)
    }

    func review(files: TranscriptFiles, url: String, settings: AppSettings) async throws -> TranscriptFiles {
        guard let json = Self.savedTranscriptJSON(files) else {
            return try await review(url: url, settings: settings)
        }
        guard !settings.rewriteCommand.isEmpty else {
            throw TranscriptionRunnerError.rewriteCommandMissing
        }
        let paths = try await outputPaths(arguments: Self.rewriteFromArguments(json: json, settings: settings), settings: settings)
        let output = try Self.files(from: paths, mode: .review, formatCount: settings.effectiveFormats.count)
        guard output.reviewed != nil else { throw TranscriptionRunnerError.missingOutput }
        return output
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
            let progress = self.progress
            result = try await Self.execute(executable: settings.yttExecutable, arguments: arguments) { line in
                progress.send(line)
            }
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

    /// Drains a pipe while the child runs, optionally reporting each line.
    ///
    /// Reading only after exit deadlocks once the child fills the pipe
    /// buffer (~64 KB): it blocks on write and never terminates.
    private final class PipeDrain: @unchecked Sendable {
        private let lock = NSLock()
        private var data = Data()
        private var pending = Data()
        private let finished = DispatchSemaphore(value: 0)

        init(_ pipe: Pipe, onLine: (@Sendable (String) -> Void)? = nil) {
            pipe.fileHandleForReading.readabilityHandler = { [self] handle in
                let chunk = handle.availableData
                guard !chunk.isEmpty else {
                    handle.readabilityHandler = nil
                    lock.lock()
                    let rest = String(decoding: pending, as: UTF8.self).trimmingCharacters(in: .whitespaces)
                    pending = Data()
                    lock.unlock()
                    if !rest.isEmpty { onLine?(rest) }
                    finished.signal()
                    return
                }
                lock.lock()
                data.append(chunk)
                var lines: [String] = []
                if onLine != nil {
                    pending.append(chunk)
                    // \r too: progress bars redraw one line with carriage returns.
                    while let end = pending.firstIndex(where: { $0 == 0x0A || $0 == 0x0D }) {
                        lines.append(String(decoding: pending[pending.startIndex..<end], as: UTF8.self))
                        pending.removeSubrange(pending.startIndex...end)
                    }
                }
                lock.unlock()
                for line in lines {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    if !trimmed.isEmpty { onLine?(trimmed) }
                }
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
    // optional ASR tools) on PATH, so Homebrew locations are prepended here,
    // plus ~/.local/bin where `pipx install mlx-whisper` puts its commands.
    static func processEnvironment(base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        let home = base["HOME"] ?? NSHomeDirectory()
        let pipxBin = (home as NSString).appendingPathComponent(".local/bin")
        let toolDirectories = ["/opt/homebrew/bin", "/usr/local/bin", pipxBin, "/usr/bin", "/bin"]
        var env = base
        let existing = (base["PATH"] ?? "").split(separator: ":").map(String.init)
        env["PATH"] = (toolDirectories + existing.filter { !toolDirectories.contains($0) }).joined(separator: ":")
        return env
    }

    /// Lets the drain threads hit EOF when the process never launched.
    private static func closeWriters(_ pipes: Pipe...) {
        for pipe in pipes { try? pipe.fileHandleForWriting.close() }
    }

    /// Stops `ytt` and everything it started.
    ///
    /// `ytt` leads its own process group (`YTT_PROCESS_GROUP=1`), so one
    /// signal to the group also stops yt-dlp, ffmpeg and Whisper, which
    /// would otherwise keep running after a cancel. SIGTERM lets ytt delete
    /// its temp audio; anything still alive after 5 seconds is killed.
    static func stop(_ process: Process) {
        guard process.isRunning else { return }
        let pid = process.processIdentifier
        if kill(-pid, SIGTERM) != 0 {
            process.terminate()  // not a group leader yet: signal ytt alone
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 5) {
            _ = kill(-pid, SIGKILL)
            if process.isRunning { _ = kill(pid, SIGKILL) }
        }
    }

    static func execute(
        executable: URL,
        arguments: [String],
        onStderrLine: (@Sendable (String) -> Void)? = nil
    ) async throws -> ProcessResult {
        let cancellationState = ProcessCancellationState()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                let process = Process()
                let outPipe = Pipe()
                let errPipe = Pipe()
                // Drain from before launch so the termination handler can
                // never run ahead of the readers.
                let outDrain = PipeDrain(outPipe)
                let errDrain = PipeDrain(errPipe, onLine: onStderrLine)
                process.executableURL = executable
                process.arguments = arguments
                var environment = Self.processEnvironment()
                environment["YTT_PROCESS_GROUP"] = "1"
                process.environment = environment
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
                    if cancellationState.isCancelled {
                        Self.stop(process)
                    }
                } catch {
                    Self.closeWriters(outPipe, errPipe)
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: {
            guard let process = cancellationState.cancel() else { return }
            Self.stop(process)
        })
    }
}

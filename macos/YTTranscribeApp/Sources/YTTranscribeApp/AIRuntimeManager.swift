// [AI-GENERATED] Claude Code agent; pending human review.
import Foundation
import Observation

/// Installs, updates and removes the app's private AI runtime, and reports
/// progress to the setup screens. One instance is shared by the whole app.
@MainActor
@Observable
final class AIRuntimeManager {
    enum Phase: Equatable {
        case idle
        /// `fraction` is overall progress from 0 to 1.
        case working(step: String, detail: String, fraction: Double)
        case failed(String)
        case finished
    }

    let layout: AIRuntimeLayout
    private(set) var status: AIRuntimeStatus
    private(set) var phase: Phase = .idle
    /// The last lines uv and Python printed, for "Show Details".
    private(set) var log: [String] = []
    private var task: Task<Void, Never>?

    var isWorking: Bool {
        if case .working = phase { return true }
        return false
    }

    init(layout: AIRuntimeLayout = .standard) {
        self.layout = layout
        status = AIRuntime.status(layout: layout)
    }

    func refresh() {
        status = AIRuntime.status(layout: layout)
    }

    /// Builds the runtime with `components`, then optionally downloads `model`.
    /// Safe to call again to repair or update: the working environment is only
    /// replaced once the new one has been built and checked.
    func install(components: Set<AIComponent>, downloadModel model: String?) {
        guard !isWorking else { return }
        var wanted = components
        wanted.insert(.enhancement)
        guard let steps = AIRuntime.installSteps(layout: layout, components: wanted),
              let lock = layout.lockFile(for: wanted), let digest = AIRuntime.digest(of: lock) else {
            phase = .failed("This copy of the app was built without the AI installer. Download the app again, or set a custom command below.")
            return
        }
        let modelStep = model.flatMap { AIRuntime.modelDownloadStep(layout: layout, model: $0) }
        start(steps: steps, modelStep: modelStep, model: model,
              manifest: AIRuntimeManifest(lockDigest: digest, components: AIComponent.allCases.filter { wanted.contains($0) },
                                          installedAt: Date(), uvVersion: AIRuntime.uvVersion))
    }

    /// Downloads `model` with the installed runtime, without rebuilding it.
    func downloadModel(_ model: String) {
        guard !isWorking, status.isReady, let step = AIRuntime.modelDownloadStep(layout: layout, model: model) else { return }
        start(steps: [], modelStep: step, model: model, manifest: nil)
    }

    private func start(steps: [AIRuntimeStep], modelStep: AIRuntimeStep?, model: String?, manifest: AIRuntimeManifest?) {
        log = []
        task = Task { [self, layout] in
            let total = Double(steps.count + (modelStep == nil ? 0 : 1))
            do {
                try FileManager.default.createDirectory(at: layout.root, withIntermediateDirectories: true)
                try FileManager.default.createDirectory(at: layout.cache, withIntermediateDirectories: true)
                for (index, step) in steps.enumerated() {
                    phase = .working(step: step.title, detail: "", fraction: Double(index) / total)
                    try await run(step, layout: layout) { [weak self] line in
                        self?.show(line, step: step.title, fraction: Double(index) / total)
                    }
                }
                if let manifest {
                    try AIRuntime.promoteStaging(layout: layout)
                    try AIRuntime.writeManifest(manifest, layout: layout)
                    refresh()
                }
                if let modelStep {
                    let base = Double(steps.count) / total
                    phase = .working(step: modelStep.title, detail: model ?? "", fraction: base)
                    try await run(modelStep, layout: layout) { [weak self] line in
                        if let part = AIRuntime.downloadFraction(fromLine: line) {
                            let percent = Int((part * 100).rounded())
                            self?.phase = .working(step: modelStep.title, detail: "\(model ?? "") · \(percent)%", fraction: base + part / total)
                        } else if !line.hasPrefix("{") {
                            self?.append(line)
                        }
                    }
                }
                phase = .finished
            } catch is CancellationError {
                try? FileManager.default.removeItem(at: layout.staging)
                refresh()
                phase = .failed(status.isReady
                    ? "Cancelled. On-device AI is installed; the model downloads the first time you press Enhance."
                    : "Setup was cancelled. Nothing was changed.")
            } catch {
                try? FileManager.default.removeItem(at: layout.staging)
                refresh()
                phase = .failed(error.localizedDescription)
            }
            task = nil
        }
    }

    func cancel() {
        task?.cancel()
    }

    /// Deletes the runtime (Python, packages and uv's cache). Downloaded
    /// models stay in the Hugging Face cache, shared with other tools.
    func remove() {
        guard !isWorking else { return }
        let fm = FileManager.default
        do {
            if fm.fileExists(atPath: layout.root.path) { try fm.removeItem(at: layout.root) }
            if fm.fileExists(atPath: layout.cache.path) { try fm.removeItem(at: layout.cache) }
            phase = .idle
        } catch {
            phase = .failed("Could not remove the AI runtime: \(error.localizedDescription)")
        }
        refresh()
    }

    func dismissResult() {
        if !isWorking { phase = .idle }
    }

    private func show(_ line: String, step: String, fraction: Double) {
        append(line)
        phase = .working(step: step, detail: line, fraction: fraction)
    }

    private func append(_ line: String) {
        log.append(line)
        if log.count > 400 { log.removeFirst(log.count - 400) }
    }

    private func run(_ step: AIRuntimeStep, layout: AIRuntimeLayout, onLine: @escaping @MainActor (String) -> Void) async throws {
        let env = AIRuntime.environment(layout: layout, base: TranscriptionRunner.processEnvironment())
        let result = try await LineStreamingProcess.run(executable: step.executable, arguments: step.arguments, environment: env) { line in
            Task { @MainActor in onLine(line) }
        }
        try Task.checkCancellation()
        guard result.status == 0 else {
            throw AIRuntimeError.stepFailed(step: step.title, status: result.status, output: result.lastLines.joined(separator: "\n"))
        }
    }
}

enum AIRuntimeError: LocalizedError {
    case stepFailed(step: String, status: Int32, output: String)

    var errorDescription: String? {
        switch self {
        case let .stepFailed(step, status, output):
            let hint = "Check your internet connection and try again."
            return output.isEmpty
                ? "\(step) failed (status \(status)). \(hint)"
                : "\(step) failed (status \(status)). \(hint)\n\n\(output)"
        }
    }
}

/// Runs a process and hands each line of stdout and stderr to `onLine` as it
/// arrives. Lines split on `\n` and `\r`, so progress bars come through too.
enum LineStreamingProcess {
    private final class LineBuffer: @unchecked Sendable {
        private let lock = NSLock()
        private var pending = Data()

        /// Appends `data` and returns the complete lines it finished.
        func feed(_ data: Data) -> [String] {
            lock.lock()
            defer { lock.unlock() }
            pending.append(data)
            var lines: [String] = []
            while let index = pending.firstIndex(where: { $0 == 0x0A || $0 == 0x0D }) {
                let line = String(decoding: pending[pending.startIndex..<index], as: UTF8.self)
                pending.removeSubrange(pending.startIndex...index)
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if !trimmed.isEmpty { lines.append(trimmed) }
            }
            return lines
        }

        func flush() -> String? {
            lock.lock()
            defer { lock.unlock() }
            let rest = String(decoding: pending, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            pending = Data()
            return rest.isEmpty ? nil : rest
        }
    }

    private final class ProcessBox: @unchecked Sendable {
        let process = Process()
        private let lock = NSLock()
        private var tail: [String] = []

        func remember(_ line: String) {
            lock.lock()
            defer { lock.unlock() }
            tail.append(line)
            if tail.count > 8 { tail.removeFirst() }
        }

        var lastLines: [String] {
            lock.lock()
            defer { lock.unlock() }
            return tail
        }
    }

    struct Outcome {
        let status: Int32
        /// The last few lines printed, for error messages.
        let lastLines: [String]
    }

    static func run(executable: URL, arguments: [String], environment: [String: String],
                    onLine: @escaping @Sendable (String) -> Void) async throws -> Outcome {
        let box = ProcessBox()
        let deliver: @Sendable (String) -> Void = { line in
            box.remember(line)
            onLine(line)
        }
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Outcome, Error>) in
                guard !Task.isCancelled else {
                    continuation.resume(throwing: CancellationError())
                    return
                }
                let process = box.process
                process.executableURL = executable
                process.arguments = arguments
                process.environment = environment
                let pipes = [Pipe(), Pipe()]
                process.standardOutput = pipes[0]
                process.standardError = pipes[1]
                let group = DispatchGroup()
                for pipe in pipes {
                    let buffer = LineBuffer()
                    group.enter()
                    pipe.fileHandleForReading.readabilityHandler = { handle in
                        let data = handle.availableData
                        if data.isEmpty {
                            handle.readabilityHandler = nil
                            if let rest = buffer.flush() { deliver(rest) }
                            group.leave()
                        } else {
                            buffer.feed(data).forEach(deliver)
                        }
                    }
                }
                process.terminationHandler = { finished in
                    // Deliver the last lines before reporting the status.
                    group.notify(queue: .global()) {
                        continuation.resume(returning: Outcome(status: finished.terminationStatus, lastLines: box.lastLines))
                    }
                }
                do {
                    try process.run()
                } catch {
                    for pipe in pipes {
                        pipe.fileHandleForReading.readabilityHandler = nil
                        try? pipe.fileHandleForWriting.close()
                    }
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: {
            if box.process.isRunning { box.process.terminate() }
        })
    }
}

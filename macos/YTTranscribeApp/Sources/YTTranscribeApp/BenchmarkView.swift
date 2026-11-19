import SwiftUI

/// Runs `ytt demo` on a copyright-free sample and lets the user pick models.
struct BenchmarkView: View {
    let model: TranscriptionViewModel
    @State private var report: BenchmarkReport?
    @State private var running = false
    @State private var download = false
    @State private var errorText: String?
    @State private var appliedText: String?
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Benchmark")
                .font(.largeTitle.weight(.semibold))
            Text(
                "Times every installed speech engine and LLM on a short sample and recommends the best fit for this Mac. "
                    + "The sample is a script written for this app and voiced on your Mac, so no video or copyrighted audio is used."
            )
            .foregroundStyle(.secondary)
            HStack {
                Button(running ? "Running…" : "Run Benchmark") { start() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(running)
                if running {
                    ProgressView().controlSize(.small)
                    Button("Cancel") { task?.cancel() }
                }
                Spacer()
                Toggle("Download missing models", isOn: $download)
                    .disabled(running)
                    .help("Downloads MLX models that are not on this Mac yet. Some are several GB.")
            }
            if model.settings.rewriteCommand.isEmpty {
                Text("To compare LLMs, set up the built-in AI model in Settings → Enhancement.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let errorText {
                Text(errorText).foregroundStyle(.red).textSelection(.enabled)
            }
            if let appliedText {
                Label(appliedText, systemImage: "checkmark.circle").foregroundStyle(.green)
            }
            if let report {
                ScrollView { results(report) }
            }
            Spacer(minLength: 0)
        }
        .padding(24)
    }

    @ViewBuilder
    private func results(_ report: BenchmarkReport) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(systemLine(report)).font(.callout).foregroundStyle(.secondary)
            recommended(report.recommendation)
            Text("Speech to text").font(.headline)
            if let asrError = report.asrError {
                Text(asrError).foregroundStyle(.secondary)
            }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                GridRow {
                    Text("Engine").bold()
                    Text("Model").bold()
                    Text("Time").bold()
                    Text("Speed").bold()
                    Text("WER").bold()
                    Text("")
                }
                ForEach(report.asr) { row in
                    GridRow {
                        Text(row.engine)
                        Text(row.model)
                        if row.isMeasured {
                            Text(BenchmarkReport.seconds(row.seconds))
                            Text(BenchmarkReport.speed(row.realtimeX))
                            Text(BenchmarkReport.percent(row.wer))
                            Button("Use") { applyASR(engine: row.engine, model: row.model) }
                        } else {
                            Text(row.reason ?? row.status)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                                .gridCellColumns(4)
                        }
                    }
                }
            }
            Text("LLM cleanup").font(.headline)
            Text("Errors left after fixing a garbled copy of the sample. Words ignores case and punctuation; strict counts them.")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let note = report.llmNote {
                Text(note).foregroundStyle(.secondary)
            }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                GridRow {
                    Text("Model").bold()
                    Text("Time").bold()
                    Text("Words").bold()
                    Text("Strict").bold()
                    Text("")
                }
                ForEach(report.llm) { row in
                    GridRow {
                        Text(row.shortName)
                        if row.isMeasured {
                            Text(BenchmarkReport.seconds(row.seconds))
                            Text(BenchmarkReport.percent(row.wer))
                            Text(BenchmarkReport.percent(row.strict))
                            Button("Use") { applyLLM(row.model) }
                                .disabled(model.settings.rewriteCommand.isEmpty)
                        } else {
                            Text(row.reason ?? row.status)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                                .gridCellColumns(4)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func recommended(_ rec: BenchmarkReport.Recommendation) -> some View {
        GroupBox("Recommended for this Mac") {
            VStack(alignment: .leading, spacing: 6) {
                Text("Speech: \(rec.asr.engine) · \(rec.asr.model)").bold()
                Text(rec.asr.reason).font(.caption).foregroundStyle(.secondary)
                Text("LLM: \(rec.llm.model.replacingOccurrences(of: "mlx-community/", with: ""))").bold()
                Text(rec.llm.reason).font(.caption).foregroundStyle(.secondary)
                Button("Use Recommended") {
                    applyASR(engine: rec.asr.engine, model: rec.asr.model)
                    if !model.settings.rewriteCommand.isEmpty { applyLLM(rec.llm.model) }
                    appliedText = model.settings.rewriteCommand.isEmpty
                        ? "Using \(rec.asr.engine) · \(rec.asr.model)"
                        : "Using \(rec.asr.model) and \(rec.llm.model)"
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(4)
        }
    }

    private func systemLine(_ report: BenchmarkReport) -> String {
        let chip = report.system.chip ?? "This Mac"
        let ram = report.system.ramGb.map { "\($0) GB memory" } ?? "unknown memory"
        return "\(chip), \(ram). Sample: \(String(format: "%.0f", report.sample.durationS)) s, \(report.sample.words) words."
    }

    private func applyASR(engine: String, model name: String) {
        model.applyBenchmarkChoice(engine: engine, model: name)
        appliedText = "Speech model set to \(engine) · \(name)"
    }

    private func applyLLM(_ name: String) {
        model.applyBenchmarkChoice(llmModel: name)
        appliedText = "LLM set to \(name)"
    }

    private func start() {
        running = true
        errorText = nil
        appliedText = nil
        let settings = model.settings
        let download = download
        task = Task {
            do {
                let result = try await BenchmarkRunner.run(settings: settings, download: download)
                await MainActor.run { report = result }
            } catch is CancellationError {
            } catch {
                await MainActor.run { errorText = error.localizedDescription }
            }
            await MainActor.run { running = false }
        }
    }
}

// [AI-GENERATED] Claude Code agent; pending human review.
import AppKit
import SwiftUI

/// What the setup installs, in words, and the user's choices for it. Shared by
/// the setup sheet (from Enhance) and Settings › Enhancement.
struct AIRuntimeConsent: View {
    @Binding var includeSpeech: Bool
    @Binding var downloadModel: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Enhance cleans up transcripts with a language model that runs on this Mac. Nothing you transcribe leaves your Mac.")
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 4) {
                Text("To set it up, the app installs into its own folder:")
                bullet("Python \(AIRuntime.pythonVersion), a private copy that does not change any Python you already have")
                bullet("Apple's MLX and MLX-LM from PyPI, at exact versions. Each file is checked against a fingerprint that ships with the app.")
                bullet("About 100 MB to download. Remove it any time in Settings.")
            }
            .font(.callout)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            Toggle(isOn: $downloadModel) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Download the language model now")
                    Text("Qwen2.5 3B, about 1.7 GB from Hugging Face. Otherwise it downloads the first time you press Enhance.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Toggle(isOn: $includeSpeech) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Also install MLX Whisper speech recognition")
                    Text("For videos without captions. Adds about 220 MB, including PyTorch. Speech models download on first use.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func bullet(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text("•")
            Text(text)
        }
    }
}

/// Progress, result and details of an install that is running or just ended.
struct AIRuntimeProgress: View {
    let runtime: AIRuntimeManager
    @State private var showingLog = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            switch runtime.phase {
            case .idle:
                EmptyView()
            case let .working(step, detail, fraction):
                ProgressView(value: fraction) {
                    Text(step).font(.headline)
                } currentValueLabel: {
                    Text(detail.isEmpty ? " " : detail)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                HStack {
                    Spacer()
                    Button("Cancel") { runtime.cancel() }
                }
            case .finished:
                Label("On-device AI is ready", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.headline)
            case let .failed(message):
                Label {
                    Text(message).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: "exclamationmark.triangle.fill")
                }
                .foregroundStyle(.red)
            }
            if !runtime.log.isEmpty {
                DisclosureGroup("Details", isExpanded: $showingLog) {
                    ScrollView {
                        Text(runtime.log.joined(separator: "\n"))
                            .font(.caption.monospaced())
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                    .frame(height: 120)
                }
                .font(.caption)
            }
        }
    }
}

/// The sheet shown when the user presses "Set Up On-Device AI…".
struct AIRuntimeSetupSheet: View {
    let runtime: AIRuntimeManager
    let model: TranscriptionViewModel
    /// Called after a successful setup, for example to start Enhance.
    var onReady: () -> Void = {}
    @Environment(\.dismiss) private var dismiss
    @State private var includeSpeech = false
    @State private var downloadModel = true

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Set up on-device AI", systemImage: "sparkles")
                .font(.title2.weight(.semibold))
            if runtime.phase == .idle {
                AIRuntimeConsent(includeSpeech: $includeSpeech, downloadModel: $downloadModel)
            } else {
                AIRuntimeProgress(runtime: runtime)
            }
            HStack {
                Text("Installs in ~/Library/Application Support/YTTranscribe/AIRuntime")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()
                buttons
            }
        }
        .padding(24)
        .frame(width: 520)
        .onChange(of: runtime.status) { _, _ in model.updateSettings(.defaults) }
        .interactiveDismissDisabled(runtime.isWorking)
    }

    @ViewBuilder
    private var buttons: some View {
        switch runtime.phase {
        case .idle:
            Button("Not Now") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button("Install") { start() }
                .keyboardShortcut(.defaultAction)
                .disabled(!runtime.layout.canInstall)
        case .working:
            EmptyView()
        case .finished:
            Button("Done") {
                runtime.dismissResult()
                dismiss()
                onReady()
            }
            .keyboardShortcut(.defaultAction)
        case .failed:
            Button("Close") {
                runtime.dismissResult()
                dismiss()
            }
            .keyboardShortcut(.cancelAction)
            Button("Try Again") { start() }
                .keyboardShortcut(.defaultAction)
        }
    }

    private func start() {
        var components: Set<AIComponent> = [.enhancement]
        if includeSpeech { components.insert(.speech) }
        runtime.install(components: components, downloadModel: downloadModel ? (model.settings.llmModel ?? AIRuntime.defaultLLM) : nil)
    }
}

/// Settings › Enhancement: status of the runtime, and install, update,
/// repair and remove.
struct AIRuntimeSettingsSection: View {
    let runtime: AIRuntimeManager
    let model: TranscriptionViewModel
    @State private var includeSpeech = false
    @State private var downloadModel = false
    @State private var confirmingRemove = false

    var body: some View {
        Section {
            statusRow
            if runtime.phase != .idle {
                AIRuntimeProgress(runtime: runtime)
            }
            if !runtime.isWorking {
                actions
            }
        } header: {
            Text("On-device AI")
        } footer: {
            Text("Enhance uses this when the custom command below is empty. Installed in ~/Library/Application Support/YTTranscribe/AIRuntime. Models are kept in ~/.cache/huggingface, shared with other MLX tools.")
                .foregroundStyle(.secondary)
        }
        .onAppear {
            runtime.refresh()
            includeSpeech = runtime.status.components.contains(.speech)
        }
        .onChange(of: runtime.status) { _, newValue in
            includeSpeech = newValue.components.contains(.speech) || includeSpeech
            model.updateSettings(.defaults)
        }
        .confirmationDialog("Remove on-device AI?", isPresented: $confirmingRemove) {
            Button("Remove", role: .destructive) { runtime.remove() }
        } message: {
            Text("Deletes the app's private Python and MLX packages. Downloaded models stay in ~/.cache/huggingface.")
        }
    }

    @ViewBuilder
    private var statusRow: some View {
        switch runtime.status {
        case .unavailable:
            Label("This build of the app cannot install on-device AI. Use a custom command below.", systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        case .notInstalled:
            Label("Not installed", systemImage: "circle.dashed")
        case .damaged:
            Label("Needs repair: the installation is incomplete.", systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        case let .ready(components, outdated):
            Label(outdated ? "Installed. An update is available." : "Installed and ready",
                  systemImage: outdated ? "arrow.down.circle" : "checkmark.circle.fill")
                .foregroundStyle(outdated ? Color.accentColor : Color.green)
            if components.contains(.speech) {
                Text("Includes MLX Whisper speech recognition.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private var actions: some View {
        switch runtime.status {
        case .unavailable:
            EmptyView()
        case .notInstalled:
            AIRuntimeConsent(includeSpeech: $includeSpeech, downloadModel: $downloadModel)
            Button("Install On-Device AI") { install() }
        case .damaged:
            Button("Repair") { install() }
        case let .ready(_, outdated):
            Toggle("Include MLX Whisper speech recognition (about 220 MB)", isOn: $includeSpeech)
            HStack {
                if outdated || includeSpeech != runtime.status.components.contains(.speech) {
                    Button(outdated ? "Update" : "Apply") { install() }
                } else {
                    Button("Reinstall") { install() }
                }
                Button("Download Model Now") {
                    runtime.downloadModel(model.settings.llmModel ?? AIRuntime.defaultLLM)
                }
                .help("Downloads \(model.settings.llmModel ?? AIRuntime.defaultLLM) so the first Enhance does not wait for it.")
                Spacer()
                Button("Remove…", role: .destructive) { confirmingRemove = true }
            }
        }
    }

    private func install() {
        var components: Set<AIComponent> = [.enhancement]
        if includeSpeech { components.insert(.speech) }
        runtime.install(components: components, downloadModel: downloadModel ? (model.settings.llmModel ?? AIRuntime.defaultLLM) : nil)
    }
}

// [AI-GENERATED] Claude Code agent; pending human review.
import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The app's Settings window: General, Transcription and Enhancement tabs.
/// Values are written to UserDefaults as they change, under the same keys
/// `AppSettings.load` reads.
struct SettingsView: View {
    let model: TranscriptionViewModel
    @State private var draft = SettingsDraft.load()

    var body: some View {
        TabView {
            GeneralSettings(draft: $draft)
                .tabItem { Label("General", systemImage: "gearshape") }
            TranscriptionSettings(draft: $draft)
                .tabItem { Label("Transcription", systemImage: "waveform") }
            EnhancementSettings(draft: $draft, model: model)
                .tabItem { Label("Enhancement", systemImage: "sparkles") }
        }
        .frame(width: 520)
        .onChange(of: draft) { _, newValue in
            newValue.save()
            model.updateSettings(.defaults)
        }
        // Setting up the built-in model can change the command outside this window.
        .onChange(of: model.settings.rewriteCommand) { _, command in
            if (AppSettings.parseCommand(draft.rewriteCommand) ?? []) != command {
                draft.rewriteCommand = AppSettings.commandLine(command)
            }
        }
    }
}

/// The editable Settings fields, as the user typed them.
struct SettingsDraft: Equatable {
    var yttExecutable: String
    var outputDirectory: String
    var engine: ASREngine
    var asrModel: String
    var rewriteCommand: String

    static func load(from values: UserDefaults = .standard) -> SettingsDraft {
        let current = AppSettings.load(from: values, environment: ProcessInfo.processInfo.environment)
        return SettingsDraft(
            yttExecutable: current.yttExecutable.path,
            outputDirectory: current.outputDirectory.path,
            engine: current.engine,
            asrModel: current.model,
            rewriteCommand: values.string(forKey: "rewriteCommand")
                ?? ProcessInfo.processInfo.environment["YTT_REWRITE_COMMAND"] ?? ""
        )
    }

    func save(to values: UserDefaults = .standard) {
        // The bundled copy's path changes when the app moves, so it is never
        // saved; an empty key falls back to it.
        if yttExecutable == AppSettings.bundledExecutable?.path {
            values.removeObject(forKey: "yttExecutable")
        } else {
            values.set(yttExecutable, forKey: "yttExecutable")
        }
        values.set(outputDirectory, forKey: "outputDirectory")
        values.set(engine.rawValue, forKey: "asrEngine")
        values.set(asrModel, forKey: "asrModel")
        values.set(rewriteCommand, forKey: "rewriteCommand")
    }

    /// Whether the command's program can be found: an absolute path must be
    /// executable; a bare name is looked up on the usual Homebrew and system paths.
    static func programExists(_ command: String) -> Bool? {
        guard let program = AppSettings.parseCommand(command)?.first, !program.isEmpty else { return nil }
        let fm = FileManager.default
        if program.hasPrefix("/") || program.hasPrefix("~") {
            let path = (program as NSString).expandingTildeInPath
            return fm.isExecutableFile(atPath: path) || (path.hasSuffix(".pyz") && fm.fileExists(atPath: path))
        }
        let searchPaths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        return searchPaths.contains { fm.isExecutableFile(atPath: "\($0)/\(program)") }
    }
}

/// A green or orange line saying whether a path or program was found.
private struct FoundStatus: View {
    let found: Bool?
    let foundText: String
    let missingText: String

    var body: some View {
        if let found {
            Label(found ? foundText : missingText,
                  systemImage: found ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .font(.caption)
                .foregroundStyle(found ? Color.green : Color.orange)
        }
    }
}

private struct GeneralSettings: View {
    @Binding var draft: SettingsDraft
    @State private var choosingFolder = false

    var body: some View {
        Form {
            Section {
                LabeledContent("Save transcripts in") {
                    HStack {
                        Text(draft.outputDirectory)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .foregroundStyle(.secondary)
                            .help(draft.outputDirectory)
                        Button("Choose…") { choosingFolder = true }
                    }
                }
                Button("Show in Finder") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: draft.outputDirectory, isDirectory: true))
                }
                .disabled(!FileManager.default.fileExists(atPath: draft.outputDirectory))
            } header: {
                Text("Output")
            }
            Section {
                TextField("ytt executable", text: $draft.yttExecutable)
                FoundStatus(
                    found: FileManager.default.fileExists(atPath: (draft.yttExecutable as NSString).expandingTildeInPath),
                    foundText: "Found",
                    missingText: "Not found. The app normally uses the copy bundled inside it."
                )
                if let bundled = AppSettings.bundledExecutable, bundled.path != draft.yttExecutable {
                    Button("Use the Bundled Copy") { draft.yttExecutable = bundled.path }
                }
            } header: {
                Text("Command-line tool")
            }
        }
        .formStyle(.grouped)
        .fileImporter(isPresented: $choosingFolder, allowedContentTypes: [.folder]) { result in
            if case let .success(url) = result { draft.outputDirectory = url.path }
        }
    }
}

private struct TranscriptionSettings: View {
    @Binding var draft: SettingsDraft

    var body: some View {
        Form {
            Section {
                Picker("Speech engine", selection: $draft.engine) {
                    ForEach(ASREngine.allCases) { Text($0.label).tag($0) }
                }
                Picker("Speech model", selection: $draft.asrModel) {
                    ForEach(ASRModel.names, id: \.self) { Text($0).tag($0) }
                    if !ASRModel.names.contains(draft.asrModel) {
                        Text(draft.asrModel).tag(draft.asrModel)
                    }
                }
            } header: {
                Text("Speech recognition")
            } footer: {
                Text("Used only when a video has no usable captions. MLX needs `pipx install mlx-whisper`; its models download on first use. The Benchmark screen recommends a model for this Mac.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }
}

private struct EnhancementSettings: View {
    @Binding var draft: SettingsDraft
    let model: TranscriptionViewModel

    var body: some View {
        Form {
            Section {
                BuiltInModelStatus(model: model, showsManagement: true)
            } header: {
                Text("Built-in AI model")
            } footer: {
                Text("One click installs MLX-LM with a private copy of Python in ~/Library/Application Support/YTTranscribe/AI, then downloads the Qwen2.5 3B model (about 1.7 GB) to the shared Hugging Face cache. Nothing is installed system-wide. Needs Apple silicon and about 2.5 GB of free space.")
                    .foregroundStyle(.secondary)
            }
            Section {
                TextField("Local rewrite command", text: $draft.rewriteCommand, prompt: Text("ollama run llama3"))
                FoundStatus(
                    found: SettingsDraft.programExists(draft.rewriteCommand),
                    foundText: "Program found",
                    missingText: "Program not found on the usual paths. Use its full path if it is installed elsewhere."
                )
            } header: {
                Text("Rewrite command")
            } footer: {
                Text("Executable and arguments. The built-in model fills this in for you; change it to use another tool. After a transcript is saved, the app can run this command to create an enhanced copy, then show every change for review. Leave empty to turn enhancement off.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }
}

/// State of the built-in AI model, with Set Up, Cancel, and (in Settings) Use and Remove.
struct BuiltInModelStatus: View {
    let model: TranscriptionViewModel
    var showsManagement = false
    @State private var confirmingRemoval = false
    @State private var removalError: String?

    private var installer: EnhancementInstaller { model.enhancement }

    var body: some View {
        if !EnhancementSetup.isSupported {
            Label("The built-in AI model needs a Mac with Apple silicon.", systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        } else {
            switch installer.phase {
            case .notInstalled:
                setUpRow(message: "Not installed. Downloads about 2.5 GB, once.")
            case let .failed(message):
                VStack(alignment: .leading, spacing: 6) {
                    Label("Setup didn't finish", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    Text(message)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Button("Try Again") { model.setUpEnhancement() }
                }
            case let .installing(step, detail):
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(step)
                        if !detail.isEmpty {
                            Text(detail).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Button("Cancel") { installer.cancel() }
                }
            case .installed:
                installedRow
            }
        }
    }

    private func setUpRow(message: String) -> some View {
        HStack {
            Text(message).foregroundStyle(.secondary)
            Spacer()
            Button("Set Up AI Enhancement") { model.setUpEnhancement() }
                .appPrimaryButtonStyle()
        }
    }

    private var installedRow: some View {
        HStack {
            Label("Installed", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
            if !installer.setup.isBuiltIn(model.settings.rewriteCommand) {
                Text("Not in use").foregroundStyle(.secondary)
            }
            Spacer()
            if showsManagement {
                if !installer.setup.isBuiltIn(model.settings.rewriteCommand) {
                    Button("Use Built-in Model") { model.useBuiltInEnhancement() }
                }
                Button("Remove…", role: .destructive) { confirmingRemoval = true }
            }
        }
        .confirmationDialog("Remove the built-in AI model?", isPresented: $confirmingRemoval) {
            Button("Remove", role: .destructive) {
                do { try model.removeEnhancement() } catch { removalError = error.localizedDescription }
            }
        } message: {
            Text("This deletes the private Python and MLX-LM. Downloaded language models stay in the Hugging Face cache (~/.cache/huggingface).")
        }
        .alert("Couldn't remove the built-in AI model", isPresented: Binding(
            get: { removalError != nil }, set: { if !$0 { removalError = nil } }
        )) {
            Button("OK") { removalError = nil }
        } message: {
            Text(removalError ?? "")
        }
    }
}

#Preview {
    SettingsView(model: TranscriptionViewModel(settings: .defaults))
}

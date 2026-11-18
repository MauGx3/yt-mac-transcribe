import AppKit
import SwiftUI

enum InputMode: String, CaseIterable, Identifiable {
    case video = "Video"
    case playlist = "Playlist"
    case batch = "Batch"

    var id: String { rawValue }
}

struct ContentView: View {
    let model: TranscriptionViewModel
    @State private var url = ""
    @State private var batchText = ""
    @State private var mode: InputMode = .video
    @State private var showingReviewPrompt = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("YouTube Transcripts")
                .font(.largeTitle.weight(.semibold))
            Picker("Input", selection: $mode) {
                ForEach(InputMode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .disabled(isBusy)
            if mode == .batch {
                TextEditor(text: $batchText)
                    .font(.body.monospaced())
                    .frame(minHeight: 90, maxHeight: 140)
                    .border(Color.secondary.opacity(0.4))
                    .disabled(isBusy)
                Text("One URL per line. Text after # is ignored.").font(.caption).foregroundStyle(.secondary)
            } else {
                TextField(mode == .playlist ? "Paste a YouTube playlist URL" : "Paste one YouTube URL", text: $url)
                    .textFieldStyle(.roundedBorder)
                    .disabled(isBusy)
                    .onSubmit { submit() }
            }
            formatPicker
            HStack {
                Button("Transcribe") { submit() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isBusy || !hasInput)
                if isBusy {
                    ProgressView()
                    Button("Cancel") { model.cancel() }
                }
            }
            statusView
            if case let .completedBatch(summary) = model.state {
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting(summary.files.flatMap { [$0.original] + $0.extras })
                }
            }
            if case let .completed(files) = model.state {
                HStack {
                    Button("Open Original") { NSWorkspace.shared.open(files.original) }
                    if let reviewed = files.reviewed {
                        Button("Open Reviewed") { NSWorkspace.shared.open(reviewed) }
                    }
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([files.original] + (files.reviewed.map { [$0] } ?? [])) }
                }
                Text(files.original.path).font(.caption).textSelection(.enabled)
                if let reviewed = files.reviewed {
                    Text(reviewed.path).font(.caption).textSelection(.enabled)
                }
            }
            Spacer()
        }
        .padding(24)
        .confirmationDialog(
            "Would you like to create a reviewed version using your local model?",
            isPresented: $showingReviewPrompt,
            titleVisibility: .visible
        ) {
            Button("Create Reviewed Version") {
                model.beginReview()
            }
            .disabled(!model.canReview)
            Button("Keep Original Only", role: .cancel) { model.declineReview() }
        } message: {
            Text(model.canReview ? "The original transcript is saved. The reviewed transcript will be saved alongside it." : "Configure a local rewrite command in Settings to create a reviewed copy.")
        }
        .onChange(of: model.state) { state in
            if case .awaitingReviewChoice = state { showingReviewPrompt = true }
        }
    }

    private var formatPicker: some View {
        HStack(spacing: 14) {
            Text("Formats").foregroundStyle(.secondary)
            ForEach(OutputFormat.allCases) { format in
                Toggle(format.rawValue, isOn: Binding(
                    get: { model.formats.contains(format) },
                    set: { isOn in
                        let updated = isOn ? model.formats + [format] : model.formats.filter { $0 != format }
                        // Keep at least one format selected.
                        if !updated.isEmpty { model.setFormats(updated) }
                    }
                ))
                .toggleStyle(.checkbox)
            }
        }
        .disabled(isBusy)
    }

    private var hasInput: Bool {
        switch mode {
        case .batch: return !URLInput.parse(batchText).isEmpty
        default: return !url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private var isBusy: Bool {
        switch model.state {
        case .transcribing, .rewriting: return true
        default: return false
        }
    }

    @ViewBuilder
    private var statusView: some View {
        switch model.state {
        case .idle: Text("Enter a video URL to create a transcript.").foregroundStyle(.secondary)
        case .transcribing: Text("Transcribing…")
        case .awaitingReviewChoice: Text("Original transcript saved. Choose whether to create a reviewed copy.")
        case .rewriting: Text("Reviewing transcript locally…")
        case .completed(let files): Text(files.reviewed == nil ? "Original transcript ready." : "Original and reviewed transcripts ready.")
        case .completedBatch(let summary):
            switch summary.kind {
            case .playlist: Text("\(summary.files.count) transcripts saved from the playlist. Find them in the Library tab.")
            default: Text("\(summary.files.count) of \(summary.requested) videos transcribed. Find them in the Library tab.")
            }
        case .failed(let message): Label(message, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
        }
    }

    private func submit() {
        guard !isBusy, hasInput else { return }
        switch mode {
        case .video:
            model.begin(url: url.trimmingCharacters(in: .whitespacesAndNewlines))
        case .playlist:
            model.beginBatch(urls: [url.trimmingCharacters(in: .whitespacesAndNewlines)], playlist: true)
        case .batch:
            model.beginBatch(urls: URLInput.parse(batchText), playlist: false)
        }
    }
}

// [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review.
#Preview {
    ContentView(model: TranscriptionViewModel(settings: .defaults))
        .frame(width: 520, height: 340)
}

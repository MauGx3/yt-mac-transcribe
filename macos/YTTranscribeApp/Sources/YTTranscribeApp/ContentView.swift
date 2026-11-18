import AppKit
import SwiftUI

enum InputMode: String, CaseIterable, Identifiable {
    case video = "Video"
    case playlist = "Playlist"
    case batch = "Batch"

    var id: String { rawValue }
}

struct ContentView: View {
    @ObservedObject var model: TranscriptionViewModel
    @State private var url = ""
    @State private var batchText = ""
    @State private var mode: InputMode = .video
    @State private var showingReviewPrompt = false
    @State private var reviewSession: ReviewViewModel?
    @State private var reviewLoadError: String?

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
                    if let review = files.review {
                        Button("Review Changes") { openReview(review) }
                            .keyboardShortcut("r", modifiers: .command)
                    }
                    if let reviewed = files.reviewed {
                        Button("Open Enhanced") { NSWorkspace.shared.open(reviewed) }
                    }
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([files.original] + (files.reviewed.map { [$0] } ?? [])) }
                }
                Text(files.original.path).font(.caption).textSelection(.enabled)
                if let reviewed = files.reviewed {
                    Text(reviewed.path).font(.caption).textSelection(.enabled)
                }
                if let reviewLoadError {
                    Label(reviewLoadError, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
            }
            Spacer()
        }
        .padding(24)
        .sheet(item: $reviewSession) { session in
            ReviewView(model: session)
        }
        .confirmationDialog(
            "Would you like to create an enhanced version using your local model?",
            isPresented: $showingReviewPrompt,
            titleVisibility: .visible
        ) {
            Button("Create Enhanced Version") {
                model.beginReview()
            }
            .disabled(!model.canReview)
            Button("Keep Original Only", role: .cancel) { model.declineReview() }
        } message: {
            Text(model.canReview ? "The original transcript is saved. The enhanced transcript will be saved alongside it, and you can review each change." : "Configure a local rewrite command in Settings to create an enhanced copy.")
        }
        .onChange(of: model.state) { state in
            if case .awaitingReviewChoice = state { showingReviewPrompt = true }
            // Show the diff as soon as an enhanced copy with a review file is ready.
            if case let .completed(files) = state, let review = files.review { openReview(review) }
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
        case .awaitingReviewChoice: Text("Original transcript saved. Choose whether to create an enhanced copy.")
        case .rewriting: Text("Enhancing transcript locally…")
        case .completed(let files): Text(files.reviewed == nil ? "Original transcript ready." : "Original and enhanced transcripts ready.")
        case .completedBatch(let summary):
            switch summary.kind {
            case .playlist: Text("\(summary.files.count) transcripts saved from the playlist. Find them in the Library tab.")
            default: Text("\(summary.files.count) of \(summary.requested) videos transcribed. Find them in the Library tab.")
            }
        case .failed(let message): Label(message, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
        }
    }

    private func openReview(_ file: URL) {
        do {
            reviewSession = try ReviewViewModel(reviewFile: file)
            reviewLoadError = nil
        } catch {
            reviewLoadError = "Could not open the review file: \(error.localizedDescription)"
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
// PreviewProvider (not #Preview) keeps compatibility with the macOS 13 target.
struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView(model: TranscriptionViewModel(settings: .defaults))
            .frame(width: 520, height: 340)
    }
}

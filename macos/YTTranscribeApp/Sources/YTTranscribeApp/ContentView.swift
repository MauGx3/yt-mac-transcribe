import AppKit
import SwiftUI

struct ContentView: View {
    @ObservedObject var model: TranscriptionViewModel
    @State private var url = ""
    @State private var showingReviewPrompt = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("YouTube Transcripts")
                .font(.largeTitle.weight(.semibold))
            TextField("Paste one YouTube URL", text: $url)
                .textFieldStyle(.roundedBorder)
                .disabled(isBusy)
                .onSubmit { submit() }
            HStack {
                Button("Transcribe") { submit() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isBusy || url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if isBusy {
                    ProgressView()
                    Button("Cancel") { model.cancel() }
                }
            }
            statusView
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
                Task { await model.acceptReview() }
            }
            .disabled(!model.canReview)
            Button("Keep Original Only", role: .cancel) { model.declineReview() }
        } message: {
            Text(model.canReview ? "The original transcript is saved. The reviewed transcript will be saved alongside it." : "Configure a local rewrite command in Settings to create a reviewed copy.")
        }
        .onChange(of: model.state) { _, state in
            if case .awaitingReviewChoice = state { showingReviewPrompt = true }
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
        case .failed(let message): Label(message, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
        }
    }

    private func submit() {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        Task { await model.start(url: trimmed) }
    }
}

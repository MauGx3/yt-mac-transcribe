// [AI-GENERATED] Claude Code agent; pending human review.
import AppKit
import SwiftUI

enum InputMode: String, CaseIterable, Identifiable {
    case video = "Video"
    case playlist = "Playlist"
    case batch = "Batch"

    var id: String { rawValue }
}

/// The Transcribe screen: a floating glass composer and a card for the
/// current run below it.
struct ContentView: View {
    let model: TranscriptionViewModel
    /// Switches the sidebar to the Library.
    var showLibrary: () -> Void = {}
    @State private var url = ""
    @State private var batchText = ""
    @State private var mode: InputMode = .video
    @State private var preview: String?
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("New transcript").font(.title2.weight(.semibold))
                    Text("Paste a YouTube link. Captions are used when the video has them; otherwise the audio is transcribed on this Mac.")
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                composer
                RunCard { runCardContent }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(32)
            .frame(maxWidth: .infinity)
        }
        .background {
            LinearGradient(
                colors: [Color.accentColor.opacity(0.14), Color.clear],
                startPoint: .top,
                endPoint: .center
            )
            .ignoresSafeArea()
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) { formatsMenu }
        }
        .onChange(of: model.state) { _, state in
            // Show the diff as soon as an enhanced copy with a review file is ready.
            if case let .completed(files) = state, let review = files.review {
                openWindow(id: ReviewWindow.id, value: review)
            }
        }
        .task(id: previewSource) { preview = Self.loadPreview(previewSource) }
    }

    // MARK: Composer

    private var composer: some View {
        AppGlassContainer(spacing: 12) {
            VStack(alignment: .leading, spacing: 12) {
                Picker("Input", selection: $mode) {
                    ForEach(InputMode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                .disabled(isBusy)
                HStack(alignment: mode == .batch ? .bottom : .center, spacing: 10) {
                    input
                    Button(action: submit) {
                        Label("Transcribe", systemImage: "text.badge.plus")
                    }
                    .appPrimaryButtonStyle()
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(isBusy || !hasInput)
                }
                if mode == .batch {
                    Text("One URL per line. Text after # is ignored.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(16)
            .appGlass(in: .rect(cornerRadius: 20))
        }
        .animation(.smooth, value: mode)
    }

    @ViewBuilder
    private var input: some View {
        if mode == .batch {
            TextEditor(text: $batchText)
                .font(.body.monospaced())
                .scrollContentBackground(.hidden)
                .frame(minHeight: 90, maxHeight: 160)
                .disabled(isBusy)
        } else {
            HStack(spacing: 8) {
                Image(systemName: "link").foregroundStyle(.secondary)
                TextField(
                    mode == .playlist ? "Paste a YouTube playlist URL" : "Paste a YouTube URL",
                    text: $url
                )
                .textFieldStyle(.plain)
                .font(.title3)
                .disabled(isBusy)
                .onSubmit(submit)
            }
        }
    }

    private var formatsMenu: some View {
        Menu {
            ForEach(OutputFormat.allCases) { format in
                Toggle(format.rawValue.uppercased(), isOn: Binding(
                    get: { model.formats.contains(format) },
                    set: { isOn in
                        let updated = isOn ? model.formats + [format] : model.formats.filter { $0 != format }
                        // Keep at least one format selected.
                        if !updated.isEmpty { model.setFormats(updated) }
                    }
                ))
            }
        } label: {
            Label("Formats: " + model.formats.map { $0.rawValue }.joined(separator: ", "), systemImage: "doc.on.doc")
        }
        .help("Output formats for new transcripts")
        .disabled(isBusy)
    }

    // MARK: Run card

    @ViewBuilder
    private var runCardContent: some View {
        switch model.state {
        case .idle:
            VStack(alignment: .leading, spacing: 6) {
                Label("Ready", systemImage: "checkmark.circle").font(.headline)
                Text("Transcripts are saved in \(model.settings.outputDirectory.path) and listed in the Library.")
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        case .transcribing:
            progressRow("Transcribing…", detail: "Fetching captions, or transcribing the audio when there are none.")
        case .rewriting:
            progressRow("Enhancing transcript…", detail: "Your local model is rewriting the transcript. The original is already saved.")
        case let .awaitingReviewChoice(files):
            enhanceChoice(files)
        case let .completed(files):
            completed(files)
        case let .completedBatch(summary):
            VStack(alignment: .leading, spacing: 10) {
                Label(batchTitle(summary), systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .foregroundStyle(.green)
                HStack {
                    Button("Show in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting(summary.files.flatMap { [$0.original] + $0.extras })
                    }
                    Button("Open Library", action: showLibrary)
                }
                .appSecondaryButtonStyle()
            }
        case let .failed(message):
            VStack(alignment: .leading, spacing: 10) {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                Button("Try Again", action: submit)
                    .appSecondaryButtonStyle()
                    .disabled(!hasInput)
            }
        }
    }

    private func progressRow(_ title: String, detail: String) -> some View {
        HStack(alignment: .center, spacing: 12) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Cancel") { model.cancel() }
                .appSecondaryButtonStyle()
                .keyboardShortcut(.cancelAction)
        }
    }

    private func enhanceChoice(_ files: TranscriptFiles) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Original transcript saved", systemImage: "checkmark.circle.fill")
                .font(.headline)
                .foregroundStyle(.green)
            Text(title(of: files)).font(.title3.weight(.medium))
            Text("Create an enhanced copy with your local model? You can review every change before keeping it.")
                .foregroundStyle(.secondary)
            HStack {
                Button("Enhance") { model.beginReview() }
                    .appPrimaryButtonStyle()
                    .disabled(!model.canReview)
                Button("Keep Original Only") { model.declineReview() }
                    .appSecondaryButtonStyle()
                if !model.canReview {
                    SettingsLink { Text("Set up a rewrite command…") }
                        .buttonStyle(.link)
                }
            }
        }
    }

    private func completed(_ files: TranscriptFiles) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(files.reviewed == nil ? "Transcript ready" : "Original and enhanced transcripts ready",
                  systemImage: "checkmark.circle.fill")
                .font(.headline)
                .foregroundStyle(.green)
            Text(title(of: files)).font(.title3.weight(.medium))
            if let preview {
                Text(preview)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(8)
                    .textSelection(.enabled)
            }
            HStack {
                Button("Open") { NSWorkspace.shared.open(files.original) }
                    .appPrimaryButtonStyle()
                if let review = files.review {
                    Button("Review Changes") { openWindow(id: ReviewWindow.id, value: review) }
                        .keyboardShortcut("r", modifiers: .command)
                        .appSecondaryButtonStyle()
                }
                if let reviewed = files.reviewed {
                    Button("Open Enhanced") { NSWorkspace.shared.open(reviewed) }
                        .appSecondaryButtonStyle()
                }
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([files.original] + files.extras + (files.reviewed.map { [$0] } ?? []))
                }
                .appSecondaryButtonStyle()
            }
            Text(files.original.path)
                .font(.caption)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
        }
    }

    // MARK: Helpers

    private func title(of files: TranscriptFiles) -> String {
        TranscriptRecord.parseFileName(files.original).title
    }

    private func batchTitle(_ summary: TranscriptionViewModel.BatchSummary) -> String {
        switch summary.kind {
        case .playlist: return "\(summary.files.count) transcripts saved from the playlist"
        default: return "\(summary.files.count) of \(summary.requested) videos transcribed"
        }
    }

    /// The finished transcript to preview, when it is plain text or Markdown.
    private var previewSource: URL? {
        guard case let .completed(files) = model.state else { return nil }
        let candidates = [files.original] + files.extras
        return candidates.first { ["txt", "md"].contains($0.pathExtension.lowercased()) }
    }

    private static func loadPreview(_ url: URL?) -> String? {
        guard let url, let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : String(trimmed.prefix(900))
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

/// A solid card for run status. Content stays off the glass layer so it
/// reads cleanly.
private struct RunCard<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background(Color(nsColor: .controlBackgroundColor), in: .rect(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Color(nsColor: .separatorColor)))
    }
}

#Preview {
    ContentView(model: TranscriptionViewModel(settings: .defaults))
        .frame(width: 720, height: 520)
}

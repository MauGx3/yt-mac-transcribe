import AppKit
import SwiftUI

/// State for one review session: the document, the user's decisions, and
/// where the Reviewed copy is saved.
@MainActor
final class ReviewViewModel: ObservableObject, Identifiable {
    enum Filter: String, CaseIterable, Identifiable {
        case changes = "All changes"
        case flagged = "Only unsure"
        var id: String { rawValue }
    }

    let id = UUID()
    let document: ReviewDocument
    let reviewFile: URL
    @Published var decisions = ReviewDecisions()
    @Published var filter: Filter = .changes
    @Published private(set) var savedURL: URL?
    @Published private(set) var saveError: String?
    /// Told where the Reviewed copy went, so the library can record it.
    var onSave: (@MainActor (URL) -> Void)?

    init(document: ReviewDocument, reviewFile: URL) {
        self.document = document
        self.reviewFile = reviewFile
    }

    convenience init(reviewFile: URL) throws {
        self.init(document: try ReviewDocument.load(from: reviewFile), reviewFile: reviewFile)
    }

    var visibleSegments: [ReviewDocument.Segment] {
        document.segments.filter { filter == .flagged ? $0.isFlagged : ($0.isChanged || $0.isFlagged) }
    }

    var rejectedCount: Int { decisions.rejected.count }

    func binding(for id: HunkID) -> Binding<Bool> {
        Binding(get: { self.decisions.isAccepted(id) },
                set: { self.decisions.set(id, accepted: $0) })
    }

    func acceptAllUnflagged() {
        decisions.acceptAllUnflagged(in: document)
    }

    /// Writes the Reviewed copy. The original and Enhanced files stay as they are.
    func save() {
        let url = ReviewDocument.reviewedURL(for: reviewFile)
        do {
            try decisions.reviewedText(for: document).write(to: url, atomically: true, encoding: .utf8)
            savedURL = url
            saveError = nil
            onSave?(url)
        } catch {
            saveError = error.localizedDescription
        }
    }
}

/// Loads a review file and shows it in its own window.
struct ReviewWindow: View {
    static let id = "review"
    let reviewFile: URL
    let model: TranscriptionViewModel
    @State private var session: ReviewViewModel?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let session {
                ReviewView(model: session)
            } else if let loadError {
                ContentUnavailableView(
                    "Could Not Open the Review",
                    systemImage: "exclamationmark.triangle",
                    description: Text(loadError)
                )
            } else {
                ProgressView()
            }
        }
        .frame(minWidth: 720, minHeight: 520)
        .task(id: reviewFile) { load() }
    }

    private func load() {
        do {
            let loaded = try ReviewViewModel(reviewFile: reviewFile)
            let model = self.model
            let file = reviewFile
            loaded.onSave = { copy in model.reviewSaved(reviewFile: file, copy: copy) }
            session = loaded
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }
}

struct ReviewView: View {
    @ObservedObject var model: ReviewViewModel
    /// Position among the visible unsure segments; nil until the user moves.
    @State private var flaggedCursor: Int?

    private var flaggedSegments: [ReviewDocument.Segment] {
        model.visibleSegments.filter(\.isFlagged)
    }

    var body: some View {
        ScrollViewReader { proxy in
            List {
                Section { summary }
                ForEach(model.visibleSegments) { segment in
                    SegmentReviewRow(segment: segment, model: model)
                        .id(segment.index)
                }
            }
            .overlay {
                if model.visibleSegments.isEmpty {
                    ContentUnavailableView(
                        model.filter == .flagged ? "Nothing Marked Unsure" : "No Changes",
                        systemImage: "checkmark.circle",
                        description: Text("There is nothing to review in this view.")
                    )
                }
            }
            .onChange(of: flaggedCursor) { _, cursor in
                let flagged = flaggedSegments
                guard let cursor, !flagged.isEmpty else { return }
                let index = ((cursor % flagged.count) + flagged.count) % flagged.count
                withAnimation { proxy.scrollTo(flagged[index].index, anchor: .top) }
            }
            .onChange(of: model.filter) { _, _ in flaggedCursor = nil }
        }
        .safeAreaInset(edge: .bottom) {
            decisionBar
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
        }
        .navigationTitle(model.document.title)
        .navigationSubtitle("Enhanced → Reviewed")
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("Show", selection: $model.filter) {
                    ForEach(ReviewViewModel.Filter.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .fixedSize()
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    model.save()
                } label: {
                    Label("Save Reviewed", systemImage: "square.and.arrow.down")
                }
                .keyboardShortcut("s", modifiers: .command)
                .help("Writes the reviewed copy next to the original. The original and enhanced files stay as they are.")
            }
        }
    }

    @ViewBuilder
    private var summary: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(model.document.stats.changed) segments changed, \(model.document.stats.flagged) with unsure spots.")
                .font(.headline)
            HStack(spacing: 16) {
                FlagBadge(flag: .aiUnsure)
                FlagBadge(flag: .unclearAudio)
            }
            if !(model.document.stats.hasAIConfidence ?? model.document.stats.hasConfidence) {
                Text("This rewrite gave no confidence information, so no change is marked AI unsure.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private var positionText: String {
        let count = flaggedSegments.count
        guard count > 0 else { return "None unsure" }
        guard let cursor = flaggedCursor else { return "\(count) unsure" }
        let index = ((cursor % count) + count) % count
        return "\(index + 1) of \(count) unsure"
    }

    /// Floating bar for moving between unsure spots and finishing the review.
    private var decisionBar: some View {
        AppGlassContainer(spacing: 8) {
            HStack(spacing: 10) {
                Button {
                    flaggedCursor = (flaggedCursor ?? 0) - 1
                } label: {
                    Label("Previous Unsure", systemImage: "chevron.up")
                }
                .labelStyle(.iconOnly)
                .help("Previous unsure spot (Option-Up)")
                .keyboardShortcut(.upArrow, modifiers: .option)
                .disabled(flaggedSegments.isEmpty)
                Text(positionText)
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
                Button {
                    flaggedCursor = (flaggedCursor ?? -1) + 1
                } label: {
                    Label("Next Unsure", systemImage: "chevron.down")
                }
                .labelStyle(.iconOnly)
                .help("Next unsure spot (Option-Down)")
                .keyboardShortcut(.downArrow, modifiers: .option)
                .disabled(flaggedSegments.isEmpty)
                Divider().frame(height: 18)
                Button("Accept All Without Unsure Marks") { model.acceptAllUnflagged() }
                Spacer(minLength: 8)
                if let error = model.saveError {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.red).lineLimit(2)
                } else if let saved = model.savedURL {
                    Button("Open Reviewed") { NSWorkspace.shared.open(saved) }
                } else {
                    Text("\(model.rejectedCount) rejected").font(.callout).foregroundStyle(.secondary)
                }
            }
            .appSecondaryButtonStyle()
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .appGlass(in: Capsule())
        }
        .frame(maxWidth: 760)
    }
}

struct FlagBadge: View {
    let flag: ReviewFlag

    var body: some View {
        Label(flag.label, systemImage: flag == .aiUnsure ? "exclamationmark.triangle.fill" : "waveform")
            .font(.caption.weight(.medium))
            .foregroundColor(flag == .aiUnsure ? .orange : .blue)
    }
}

private struct SegmentReviewRow: View {
    let segment: ReviewDocument.Segment
    @ObservedObject var model: ReviewViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(timestamp).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            ForEach(Array(segment.hunks.enumerated()), id: \.offset) { index, hunk in
                HunkRow(hunk: hunk, accepted: model.binding(for: HunkID(segment: segment.index, hunk: index)))
            }
            if !segment.unclearKept.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    FlagBadge(flag: .unclearAudio)
                    Text("Unchanged, check against the audio: " + segment.unclearKept.compactMap(\.text).joined(separator: ", "))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
            Text(model.decisions.text(for: segment))
                .font(.callout)
                .textSelection(.enabled)
        }
        .padding(.vertical, 4)
    }

    private var timestamp: String {
        let seconds = segment.startMs / 1000
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
}

private struct HunkRow: View {
    let hunk: ReviewDocument.Hunk
    @Binding var accepted: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            change
            if hunk.isAIUnsure { FlagBadge(flag: .aiUnsure) }
            if hunk.isUnclearAudio { FlagBadge(flag: .unclearAudio) }
            Spacer()
            Picker("", selection: $accepted) {
                Text("Accept").tag(true)
                Text("Reject").tag(false)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 150)
        }
    }

    private var change: Text {
        let removed = Text(hunk.origText.isEmpty ? "" : hunk.origText)
            .strikethrough(true, color: .red)
            .foregroundColor(.red)
        let added = Text(hunk.newText.isEmpty ? "" : hunk.newText)
            .underline(hunk.isAIUnsure, color: .orange)
            .foregroundColor(.green)
        switch hunk.op {
        case "insert": return Text("+ ") + added
        case "delete": return Text("− ") + removed
        default: return removed + Text("  →  ") + added
        }
    }
}

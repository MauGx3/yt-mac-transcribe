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

    init(document: ReviewDocument, reviewFile: URL) {
        self.document = document
        self.reviewFile = reviewFile
    }

    convenience init(reviewFile: URL) throws {
        self.init(document: try ReviewDocument.load(from: reviewFile), reviewFile: reviewFile)
    }

    var visibleSegments: [ReviewDocument.Segment] {
        document.segments.filter { filter == .flagged ? $0.isFlagged : $0.isChanged }
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
        } catch {
            saveError = error.localizedDescription
        }
    }
}

struct ReviewView: View {
    @ObservedObject var model: ReviewViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var flaggedCursor = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            legend
            ScrollViewReader { proxy in
                List(model.visibleSegments) { segment in
                    SegmentReviewRow(segment: segment, model: model)
                        .id(segment.index)
                }
                .onChange(of: flaggedCursor) { _ in
                    let flagged = model.document.segments.filter(\.isFlagged)
                    guard !flagged.isEmpty else { return }
                    proxy.scrollTo(flagged[flaggedCursor % flagged.count].index, anchor: .top)
                }
            }
            footer
        }
        .padding(20)
        .frame(minWidth: 720, minHeight: 520)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Review: \(model.document.title)").font(.title2.weight(.semibold))
                Text("\(model.document.stats.changed) segments changed, \(model.document.stats.flagged) with unsure spots. Enhanced → Reviewed")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Picker("Show", selection: $model.filter) {
                ForEach(ReviewViewModel.Filter.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .frame(width: 240)
        }
    }

    @ViewBuilder
    private var legend: some View {
        HStack(spacing: 16) {
            FlagBadge(flag: .aiUnsure)
            FlagBadge(flag: .unclearAudio)
            if !model.document.stats.hasConfidence {
                Text("This rewrite gave no confidence information, so nothing is marked unsure.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        HStack {
            Button("Next unsure") { flaggedCursor += 1 }
                .keyboardShortcut(.downArrow, modifiers: .option)
                .disabled(model.document.stats.flagged == 0)
            Button("Accept all without unsure marks") { model.acceptAllUnflagged() }
            Spacer()
            if let saved = model.savedURL {
                Button("Open Reviewed") { NSWorkspace.shared.open(saved) }
            }
            if let error = model.saveError {
                Text(error).foregroundStyle(.red).font(.caption)
            }
            Text("\(model.rejectedCount) rejected").foregroundStyle(.secondary)
            Button("Save Reviewed") { model.save() }
                .keyboardShortcut("s", modifiers: .command)
            Button("Close") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
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

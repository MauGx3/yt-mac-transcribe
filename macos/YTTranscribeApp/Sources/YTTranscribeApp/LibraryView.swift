// [AI-GENERATED] Claude Code agent; pending human review.
import AppKit
import SwiftUI

/// Which records a Library screen lists.
enum LibraryFilter {
    case all
    case needsReview
}

private enum SearchScope: Hashable {
    case titles
    case transcripts
}

extension TranscriptRecord {
    /// Sorts Needs review first, then Reviewed, then not enhanced.
    var reviewSortKey: Int {
        switch reviewStatus {
        case .needsReview: return 0
        case .reviewed: return 1
        case .notEnhanced: return 2
        }
    }

    var formatsText: String { formats.joined(separator: ", ") }

    var isMissingFile: Bool {
        guard let file = primaryFile else { return true }
        return !FileManager.default.fileExists(atPath: file.path)
    }
}

/// Browse, search and review past transcripts.
struct LibraryView: View {
    let library: LibraryStore
    let filter: LibraryFilter
    @State private var query = ""
    @State private var scope: SearchScope = .transcripts
    @State private var selection: Set<TranscriptRecord.ID> = []
    @State private var sortOrder = [KeyPathComparator(\TranscriptRecord.createdAt, order: .reverse)]
    @State private var showInspector = true
    @Environment(\.openWindow) private var openWindow

    private var results: [TranscriptRecord] {
        library.search(query, includeContents: scope == .transcripts)
            .filter { filter == .all || $0.reviewStatus == .needsReview }
            .sorted(using: sortOrder)
    }

    private var selectedRecords: [TranscriptRecord] {
        library.records.filter { selection.contains($0.id) }
    }

    var body: some View {
        Table(results, selection: $selection, sortOrder: $sortOrder) {
            TableColumn("Title", value: \.title) { record in
                HStack(spacing: 6) {
                    Text(record.title).lineLimit(1)
                    if record.isMissingFile {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                            .help("File moved or deleted")
                    }
                }
            }
            TableColumn("Created", value: \.createdAt) { record in
                Text(record.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .foregroundStyle(.secondary)
            }
            .width(min: 120, ideal: 150)
            TableColumn("Formats", value: \.formatsText) { record in
                Text(record.formatsText).foregroundStyle(.secondary)
            }
            .width(min: 70, ideal: 100)
            TableColumn("Review", value: \.reviewSortKey) { record in
                ReviewStatusBadge(status: record.reviewStatus)
            }
            .width(min: 100, ideal: 120)
        }
        .contextMenu(forSelectionType: TranscriptRecord.ID.self) { ids in
            let records = library.records.filter { ids.contains($0.id) }
            if records.count == 1, let record = records.first {
                RecordActions(record: record, library: library, openReview: openReview)
            } else if !records.isEmpty {
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting(records.flatMap(\.allFiles))
                }
                Divider()
                Button("Remove \(records.count) from Library", role: .destructive) {
                    for record in records { library.remove(record) }
                    selection.subtract(ids)
                }
            }
        } primaryAction: { ids in
            for record in library.records where ids.contains(record.id) {
                if let file = record.primaryFile { NSWorkspace.shared.open(file) }
            }
        }
        .overlay { emptyState }
        .searchable(text: $query, placement: .toolbar, prompt: "Search transcripts")
        .searchScopes($scope) {
            Text("Transcript Text").tag(SearchScope.transcripts)
            Text("Titles and Links").tag(SearchScope.titles)
        }
        .inspector(isPresented: $showInspector) {
            inspector
                .inspectorColumnWidth(min: 240, ideal: 280, max: 380)
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if let record = selectedRecords.first, selectedRecords.count == 1, let reviewFile = record.reviewFile {
                    Button {
                        openReview(reviewFile)
                    } label: {
                        Label("Review Changes", systemImage: "text.badge.checkmark")
                    }
                    .help("Review the enhanced transcript's changes")
                }
                Button {
                    NSWorkspace.shared.activateFileViewerSelecting(selectedRecords.flatMap(\.allFiles))
                } label: {
                    Label("Show in Finder", systemImage: "folder")
                }
                .disabled(selectedRecords.isEmpty)
                Button {
                    showInspector.toggle()
                } label: {
                    Label("Inspector", systemImage: "sidebar.trailing")
                }
                .help(showInspector ? "Hide details" : "Show details")
            }
        }
    }

    @ViewBuilder
    private var emptyState: some View {
        if results.isEmpty {
            if !query.isEmpty {
                ContentUnavailableView.search(text: query)
            } else if filter == .needsReview {
                ContentUnavailableView(
                    "Nothing to Review",
                    systemImage: "checkmark.circle",
                    description: Text("Enhanced transcripts wait here until you save a reviewed copy.")
                )
            } else {
                ContentUnavailableView(
                    "No Transcripts Yet",
                    systemImage: "books.vertical",
                    description: Text("Transcripts you create appear here.")
                )
            }
        }
    }

    @ViewBuilder
    private var inspector: some View {
        if selectedRecords.count == 1, let record = selectedRecords.first {
            RecordInspector(record: record, library: library, openReview: openReview)
        } else {
            ContentUnavailableView(
                selectedRecords.isEmpty ? "No Selection" : "\(selectedRecords.count) Transcripts Selected",
                systemImage: "doc.text.magnifyingglass",
                description: Text(selectedRecords.isEmpty ? "Select a transcript to see its files and review status." : "Use the toolbar or right-click to act on all of them.")
            )
        }
    }

    private func openReview(_ reviewFile: URL) {
        openWindow(id: ReviewWindow.id, value: reviewFile)
    }
}

/// A capsule showing Needs review or Reviewed, with a symbol so it reads
/// without colour.
struct ReviewStatusBadge: View {
    let status: TranscriptRecord.ReviewStatus

    var body: some View {
        switch status {
        case .needsReview:
            badge("Needs review", systemImage: "circle.dashed", color: .orange)
        case .reviewed:
            badge("Reviewed", systemImage: "checkmark.circle.fill", color: .green)
        case .notEnhanced:
            Text("—").foregroundStyle(.tertiary).accessibilityLabel("Not enhanced")
        }
    }

    private func badge(_ title: String, systemImage: String, color: Color) -> some View {
        Label(title, systemImage: systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule())
    }
}

/// Menu items for one record, shared by the context menu.
private struct RecordActions: View {
    let record: TranscriptRecord
    let library: LibraryStore
    let openReview: (URL) -> Void

    var body: some View {
        Button("Open") { if let file = record.primaryFile { NSWorkspace.shared.open(file) } }
            .disabled(record.isMissingFile)
        if let reviewFile = record.reviewFile {
            Button(record.reviewStatus == .reviewed ? "Review Again" : "Review Changes") { openReview(reviewFile) }
        }
        if let copy = record.reviewedCopy {
            Button("Open Reviewed") { NSWorkspace.shared.open(copy) }
        }
        if let enhanced = record.reviewed {
            Button("Open Enhanced") { NSWorkspace.shared.open(enhanced) }
        }
        Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting(record.allFiles) }
            .disabled(record.isMissingFile)
        Divider()
        Button("Remove from Library", role: .destructive) { library.remove(record) }
            .help("Removes the entry from the library. Transcript files stay on disk.")
    }
}

/// Details of the selected transcript: source, files and review status.
private struct RecordInspector: View {
    let record: TranscriptRecord
    let library: LibraryStore
    let openReview: (URL) -> Void

    var body: some View {
        Form {
            Section {
                Text(record.title).font(.headline).textSelection(.enabled)
                if let link = URL(string: record.sourceURL), link.scheme?.hasPrefix("http") == true {
                    Link(record.sourceURL, destination: link).lineLimit(1).truncationMode(.middle)
                } else {
                    Text(record.sourceURL).textSelection(.enabled)
                }
                LabeledContent("Created", value: record.createdAt.formatted(date: .abbreviated, time: .shortened))
            }
            Section("Review") {
                LabeledContent("Status") { ReviewStatusBadge(status: record.reviewStatus) }
                if let reviewFile = record.reviewFile {
                    Button(record.reviewStatus == .reviewed ? "Review Again" : "Review Changes") { openReview(reviewFile) }
                        .appPrimaryButtonStyle()
                }
            }
            Section("Files") {
                if record.isMissingFile {
                    Label("The transcript file was moved or deleted.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                ForEach(record.allFiles, id: \.self) { file in
                    HStack {
                        Text(file.lastPathComponent)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .help(file.path)
                        Spacer()
                        Button {
                            NSWorkspace.shared.open(file)
                        } label: {
                            Image(systemName: "arrow.up.forward.app")
                        }
                        .buttonStyle(.borderless)
                        .help("Open")
                        .disabled(!FileManager.default.fileExists(atPath: file.path))
                        Button {
                            NSWorkspace.shared.activateFileViewerSelecting([file])
                        } label: {
                            Image(systemName: "magnifyingglass")
                        }
                        .buttonStyle(.borderless)
                        .help("Show in Finder")
                        .disabled(!FileManager.default.fileExists(atPath: file.path))
                    }
                }
            }
            Section {
                Button("Remove from Library", role: .destructive) { library.remove(record) }
                    .help("Removes the entry from the library. Transcript files stay on disk.")
            }
        }
        .formStyle(.grouped)
    }
}

#Preview {
    LibraryView(library: LibraryStore(fileURL: nil), filter: .all)
        .frame(width: 900, height: 500)
}

import AppKit
import SwiftUI

/// Browse and search past transcripts.
struct LibraryView: View {
    let library: LibraryStore
    @State private var query = ""
    @State private var searchText = true

    private var results: [TranscriptRecord] {
        library.search(query, includeContents: searchText)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                TextField("Search titles, URLs and transcript text", text: $query)
                    .textFieldStyle(.roundedBorder)
                Toggle("Search inside transcripts", isOn: $searchText)
                    .toggleStyle(.checkbox)
            }
            if results.isEmpty {
                Spacer()
                Text(library.records.isEmpty ? "Transcripts you create appear here." : "No transcripts match your search.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                Spacer()
            } else {
                List(results) { record in
                    LibraryRow(record: record, library: library)
                }
            }
        }
        .padding(24)
    }
}

private struct LibraryRow: View {
    let record: TranscriptRecord
    let library: LibraryStore

    private var missing: Bool {
        guard let file = record.primaryFile else { return true }
        return !FileManager.default.fileExists(atPath: file.path)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(record.title).font(.headline).lineLimit(1)
                if missing {
                    Label("File moved or deleted", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.orange)
                }
                Spacer()
                Text(record.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text(record.sourceURL).font(.caption).foregroundStyle(.secondary).lineLimit(1).textSelection(.enabled)
            HStack {
                Text(record.formats.joined(separator: " · ") + (record.reviewed == nil ? "" : " · reviewed"))
                    .font(.caption)
                Spacer()
                Button("Open") { if let file = record.primaryFile { NSWorkspace.shared.open(file) } }
                    .disabled(missing)
                if let reviewed = record.reviewed {
                    Button("Open Reviewed") { NSWorkspace.shared.open(reviewed) }
                }
                Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting(record.allFiles) }
                    .disabled(missing)
                Button("Remove", role: .destructive) { library.remove(record) }
                    .help("Removes the entry from the library. Transcript files stay on disk.")
            }
            .buttonStyle(.link)
        }
        .padding(.vertical, 4)
    }
}

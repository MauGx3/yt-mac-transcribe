import Combine
import Foundation

/// Output formats understood by `ytt -f`.
enum OutputFormat: String, CaseIterable, Codable, Identifiable {
    case txt, srt, vtt, json, md

    var id: String { rawValue }

    /// Dedupes, orders by `allCases`, and falls back to plain text when empty.
    static func normalized(_ formats: [OutputFormat]) -> [OutputFormat] {
        let selected = allCases.filter { formats.contains($0) }
        return selected.isEmpty ? [.txt] : selected
    }

    static func parse(_ csv: String) -> [OutputFormat] {
        normalized(csv.split(separator: ",").compactMap { OutputFormat(rawValue: $0.trimmingCharacters(in: .whitespaces)) })
    }
}

enum RunKind: String, Codable {
    case single, playlist, batch
}

/// One transcribed video, as remembered by the library.
struct TranscriptRecord: Codable, Identifiable, Equatable {
    var id: UUID
    var title: String
    var sourceURL: String
    var createdAt: Date
    var kind: RunKind
    /// Original transcript files, one per requested format.
    var files: [URL]
    var reviewed: URL?

    var primaryFile: URL? { files.first }
    var allFiles: [URL] { files + (reviewed.map { [$0] } ?? []) }
    var formats: [String] { files.map { $0.pathExtension.lowercased() } }

    /// `ytt` names multi-video output `Title [videoid].ext`.
    static func parseFileName(_ url: URL) -> (title: String, videoID: String?) {
        let stem = url.deletingPathExtension().lastPathComponent
        guard let regex = try? NSRegularExpression(pattern: #"^(.*) \[([A-Za-z0-9_-]{11})\]$"#),
              let match = regex.firstMatch(in: stem, range: NSRange(stem.startIndex..., in: stem)),
              let titleRange = Range(match.range(at: 1), in: stem),
              let idRange = Range(match.range(at: 2), in: stem) else {
            return (stem, nil)
        }
        return (String(stem[titleRange]), String(stem[idRange]))
    }

    static func make(files: TranscriptFiles, sourceURL: String, kind: RunKind, date: Date = Date()) -> TranscriptRecord {
        let parsed = parseFileName(files.original)
        let source = parsed.videoID.map { "https://www.youtube.com/watch?v=\($0)" } ?? sourceURL
        return TranscriptRecord(
            id: UUID(),
            title: parsed.title,
            sourceURL: source,
            createdAt: date,
            kind: kind,
            files: [files.original] + files.extras,
            reviewed: files.reviewed
        )
    }
}

/// Splits pasted text into URLs the same way `ytt --batch` reads files:
/// one per line, `#` starts a comment, blank lines are ignored.
enum URLInput {
    static func parse(_ text: String) -> [String] {
        text.split(whereSeparator: \.isNewline).compactMap { line in
            let stripped = line.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)
                .first.map(String.init) ?? ""
            let trimmed = stripped.trimmingCharacters(in: .whitespaces)
            return trimmed.isEmpty ? nil : trimmed
        }
    }
}

/// History of transcripts, persisted as JSON.
@MainActor
final class LibraryStore: ObservableObject {
    @Published private(set) var records: [TranscriptRecord] = []
    private let fileURL: URL?

    /// `fileURL == nil` keeps the library in memory only.
    init(fileURL: URL?) {
        self.fileURL = fileURL
        load()
    }

    static func standard() -> LibraryStore {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let directory = support.appendingPathComponent("YTTranscribe", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return LibraryStore(fileURL: directory.appendingPathComponent("library.json"))
    }

    func record(id: UUID) -> TranscriptRecord? {
        records.first { $0.id == id }
    }

    func add(_ record: TranscriptRecord) {
        records.insert(record, at: 0)
        save()
    }

    func update(_ record: TranscriptRecord) {
        guard let index = records.firstIndex(where: { $0.id == record.id }) else { return }
        records[index] = record
        save()
    }

    /// Removes the history entry only; transcript files stay on disk.
    func remove(_ record: TranscriptRecord) {
        records.removeAll { $0.id == record.id }
        save()
    }

    func search(_ query: String, includeContents: Bool) -> [TranscriptRecord] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return records }
        return records.filter { Self.matches($0, query: needle, includeContents: includeContents) }
    }

    nonisolated static func matches(_ record: TranscriptRecord, query: String, includeContents: Bool) -> Bool {
        if record.title.localizedCaseInsensitiveContains(query) || record.sourceURL.localizedCaseInsensitiveContains(query) {
            return true
        }
        guard includeContents else { return false }
        return record.allFiles.contains { file in
            // Cap how much of each file is read so huge transcripts stay cheap.
            guard let handle = try? FileHandle(forReadingFrom: file) else { return false }
            defer { try? handle.close() }
            guard let data = try? handle.read(upToCount: 4_000_000) else { return false }
            return String(decoding: data, as: UTF8.self).localizedCaseInsensitiveContains(query)
        }
    }

    private func load() {
        guard let fileURL, let data = try? Data(contentsOf: fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        if let decoded = try? decoder.decode([TranscriptRecord].self, from: data) {
            records = decoded
        }
    }

    private func save() {
        guard let fileURL else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(records) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }
}

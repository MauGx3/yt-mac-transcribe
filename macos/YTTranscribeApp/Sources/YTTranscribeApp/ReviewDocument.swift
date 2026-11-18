import Foundation

/// The `<name>.review.json` file `ytt` writes after an AI rewrite: per
/// segment, the original and enhanced text, the word-level changes between
/// them, and the spans a runner marked as uncertain.
struct ReviewDocument: Codable, Equatable {
    struct Stats: Codable, Equatable {
        let segments: Int
        let changed: Int
        let flagged: Int
        let hasConfidence: Bool

        enum CodingKeys: String, CodingKey {
            case segments, changed, flagged
            case hasConfidence = "has_confidence"
        }
    }

    struct Hunk: Codable, Equatable {
        let op: String
        let orig: [Int]
        let new: [Int]
        let origText: String
        let newText: String
        let flags: [String]

        enum CodingKeys: String, CodingKey {
            case op, orig, new, flags
            case origText = "orig_text"
            case newText = "new_text"
        }

        var isAIUnsure: Bool { flags.contains(ReviewFlag.aiUnsure.rawValue) }
        var isUnclearAudio: Bool { flags.contains(ReviewFlag.unclearAudio.rawValue) }
        var isFlagged: Bool { isAIUnsure || isUnclearAudio }
    }

    struct Segment: Codable, Equatable, Identifiable {
        let index: Int
        let startMs: Int
        let endMs: Int
        let original: String
        let enhanced: String
        let hunks: [Hunk]

        enum CodingKeys: String, CodingKey {
            case index, original, enhanced, hunks
            case startMs = "start_ms"
            case endMs = "end_ms"
        }

        var id: Int { index }
        var isChanged: Bool { !hunks.isEmpty }
        var isFlagged: Bool { hunks.contains(where: \.isFlagged) }
    }

    let version: Int
    let title: String
    let stats: Stats
    let segments: [Segment]

    static func load(from url: URL) throws -> ReviewDocument {
        try JSONDecoder().decode(ReviewDocument.self, from: Data(contentsOf: url))
    }
}

/// The two kinds of "unsure" the review screen labels separately.
enum ReviewFlag: String {
    /// The rewrite model was unsure of its own edit.
    case aiUnsure = "ai_unsure"
    /// The speech recognition was unsure what was said.
    case unclearAudio = "unclear_audio"

    var label: String {
        switch self {
        case .aiUnsure: return "AI unsure"
        case .unclearAudio: return "Unclear audio"
        }
    }
}

/// A change the user can accept or reject, addressed by segment and hunk.
struct HunkID: Hashable {
    let segment: Int
    let hunk: Int
}

/// The user's accept/reject decisions. Every change starts accepted.
struct ReviewDecisions: Equatable {
    private(set) var rejected: Set<HunkID> = []

    func isAccepted(_ id: HunkID) -> Bool { !rejected.contains(id) }

    mutating func set(_ id: HunkID, accepted: Bool) {
        if accepted { rejected.remove(id) } else { rejected.insert(id) }
    }

    /// Accepts every change that carries no unsure label.
    mutating func acceptAllUnflagged(in document: ReviewDocument) {
        for segment in document.segments {
            for (i, hunk) in segment.hunks.enumerated() where !hunk.isFlagged {
                rejected.remove(HunkID(segment: segment.index, hunk: i))
            }
        }
    }

    /// Final text of one segment: accepted changes use the enhanced words,
    /// rejected ones keep the original words.
    func text(for segment: ReviewDocument.Segment) -> String {
        let refused = Set(segment.hunks.indices.filter { rejected.contains(HunkID(segment: segment.index, hunk: $0)) })
        guard !refused.isEmpty else { return segment.enhanced }
        let a = segment.original.split(whereSeparator: \.isWhitespace).map(String.init)
        let b = segment.enhanced.split(whereSeparator: \.isWhitespace).map(String.init)
        var words: [String] = []
        var bPos = 0
        for (i, hunk) in segment.hunks.enumerated() {
            guard hunk.orig.count == 2, hunk.new.count == 2,
                  hunk.new[0] >= bPos, hunk.new[0] <= hunk.new[1], hunk.new[1] <= b.count,
                  hunk.orig[0] <= hunk.orig[1], hunk.orig[1] <= a.count else {
                return segment.enhanced  // malformed ranges: never guess
            }
            words += b[bPos..<hunk.new[0]]  // unchanged words match on both sides
            words += refused.contains(i) ? a[hunk.orig[0]..<hunk.orig[1]] : b[hunk.new[0]..<hunk.new[1]]
            bPos = hunk.new[1]
        }
        words += b[bPos...]
        return words.joined(separator: " ")
    }

    /// The Reviewed transcript as plain text, one line per segment.
    func reviewedText(for document: ReviewDocument) -> String {
        document.segments.map { text(for: $0) }.joined(separator: "\n") + "\n"
    }
}

extension ReviewDocument {
    /// `My Video.review.json` → `My Video.reviewed.txt` next to it.
    static func reviewedURL(for reviewFile: URL) -> URL {
        let name = reviewFile.lastPathComponent
        let base = name.hasSuffix(".review.json") ? String(name.dropLast(".review.json".count)) : reviewFile.deletingPathExtension().lastPathComponent
        return reviewFile.deletingLastPathComponent().appendingPathComponent(base + ".reviewed.txt")
    }
}

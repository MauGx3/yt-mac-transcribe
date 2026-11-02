import Foundation
import XCTest
@testable import YTTranscribeApp

final class AppSettingsTests: XCTestCase {
    func testCommandTokenizerPreservesQuotedArgumentsAndEscapes() {
        XCTAssertEqual(
            AppSettings.parseCommand("\"/Applications/Local Model/bin/rewrite\" --model \"small model\" escaped\\ value"),
            ["/Applications/Local Model/bin/rewrite", "--model", "small model", "escaped value"]
        )
        XCTAssertNil(AppSettings.parseCommand("\"unterminated"))
    }

    func testSettingsRoundTrip() {
        let suite = "AppSettingsTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("/tmp/ytt", forKey: "yttExecutable")
        defaults.set("\"/Applications/Local Model/bin/rewrite\" --model \"small model\"", forKey: "rewriteCommand")
        defaults.set("/tmp/transcripts", forKey: "outputDirectory")
        let loaded = AppSettings.load(from: defaults, environment: [:])
        XCTAssertEqual(loaded.yttExecutable.path, "/tmp/ytt")
        XCTAssertEqual(loaded.rewriteCommand, ["/Applications/Local Model/bin/rewrite", "--model", "small model"])
        XCTAssertEqual(loaded.outputDirectory.path, "/tmp/transcripts")
    }
}

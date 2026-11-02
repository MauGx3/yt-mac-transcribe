import Foundation
import XCTest
@testable import YTTranscribeApp

final class AppSettingsTests: XCTestCase {
    func testSettingsRoundTrip() {
        let suite = "AppSettingsTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("/tmp/ytt", forKey: "yttExecutable")
        defaults.set("ollama run local", forKey: "rewriteCommand")
        defaults.set("/tmp/transcripts", forKey: "outputDirectory")
        let loaded = AppSettings.load(from: defaults, environment: [:])
        XCTAssertEqual(loaded.yttExecutable.path, "/tmp/ytt")
        XCTAssertEqual(loaded.rewriteCommand, ["ollama", "run", "local"])
        XCTAssertEqual(loaded.outputDirectory.path, "/tmp/transcripts")
    }
}

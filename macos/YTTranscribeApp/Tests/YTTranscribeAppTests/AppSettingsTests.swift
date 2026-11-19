import Foundation
import XCTest
@testable import YTTranscribeApp

final class AppSettingsTests: XCTestCase {
    func testCommandTokenizerPreservesQuotedArgumentsAndEscapes() {
        XCTAssertEqual(
            AppSettings.parseCommand("\"/Applications/Local Model/bin/rewrite\" --model \"small model\" escaped\\ value"),
            ["/Applications/Local Model/bin/rewrite", "--model", "small model", "escaped value"]
        )
        XCTAssertNil(AppSettings.parseCommand("\"\""))
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

    func testEngineAndModelRoundTripAndDefaults() {
        let suite = "AppSettingsTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let fresh = AppSettings.load(from: defaults, environment: [:])
        XCTAssertEqual(fresh.engine, .auto)
        XCTAssertEqual(fresh.model, "small.en")

        var chosen = fresh
        chosen.engine = .mlx
        chosen.model = "base.en"
        chosen.persist(to: defaults)
        let loaded = AppSettings.load(from: defaults, environment: [:])
        XCTAssertEqual(loaded.engine, .mlx)
        XCTAssertEqual(loaded.model, "base.en")

        defaults.set("bogus", forKey: "asrEngine")
        XCTAssertEqual(AppSettings.load(from: defaults, environment: [:]).engine, .auto)
    }

    func testQuoteCommandRoundTripsThroughParser() {
        let tokens = ["/Users/me/My Tools/run.py", "--model", "it's \"big\"", "back\\slash", ""]
        XCTAssertEqual(AppSettings.parseCommand(AppSettings.quoteCommand(tokens)), tokens)
        XCTAssertEqual(AppSettings.quoteCommand(["plain", "--flag"]), "plain --flag")
    }

    func testPersistKeepsPathsWithSpaces() {
        let suite = "AppSettingsTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        var settings = AppSettings.load(from: defaults, environment: [:])
        settings.rewriteCommand = ["/Users/me/My Tools/run.py", "--model", "x"]
        settings.persist(to: defaults)
        XCTAssertEqual(AppSettings.load(from: defaults, environment: [:]).rewriteCommand, settings.rewriteCommand)
    }

    func testPersistKeepsTheTextTypedInSettings() {
        let suite = "AppSettingsTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let typed = "\"/Applications/Local Model/bin/rewrite\" --model x"
        defaults.set(typed, forKey: "rewriteCommand")
        AppSettings.load(from: defaults, environment: [:]).persist(to: defaults)
        XCTAssertEqual(defaults.string(forKey: "rewriteCommand"), typed)
    }
}

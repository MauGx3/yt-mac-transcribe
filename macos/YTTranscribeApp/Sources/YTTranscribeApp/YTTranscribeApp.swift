import SwiftUI

@main
struct YTTranscribeApp: App {
    @StateObject private var library: LibraryStore
    @StateObject private var model: TranscriptionViewModel

    init() {
        let library = LibraryStore.standard()
        _library = StateObject(wrappedValue: library)
        _model = StateObject(wrappedValue: TranscriptionViewModel(settings: .defaults, library: library))
    }

    var body: some Scene {
        WindowGroup {
            TabView {
                ContentView(model: model)
                    .tabItem { Label("Transcribe", systemImage: "text.badge.plus") }
                LibraryView(library: library)
                    .tabItem { Label("Library", systemImage: "books.vertical") }
            }
            .frame(minWidth: 560, minHeight: 480)
        }
        Settings {
            AppSettingsView(model: model)
                .frame(width: 460)
                .padding(20)
        }
    }
}

private struct AppSettingsView: View {
    @ObservedObject var model: TranscriptionViewModel
    @State private var yttExecutable = UserDefaults.standard.string(forKey: "yttExecutable") ?? "/opt/homebrew/bin/ytt"
    @State private var rewriteCommand = UserDefaults.standard.string(forKey: "rewriteCommand") ?? ProcessInfo.processInfo.environment["YTT_REWRITE_COMMAND"] ?? ""
    @State private var outputDirectory = UserDefaults.standard.string(forKey: "outputDirectory") ?? AppSettings.defaultOutputDirectory.path

    var body: some View {
        Form {
            TextField("ytt executable", text: $yttExecutable)
            TextField("Local rewrite command", text: $rewriteCommand)
                .help("Executable and arguments, for example: ollama run llama3")
            TextField("Output directory", text: $outputDirectory)
        }
        .padding()
        .onDisappear {
            UserDefaults.standard.set(yttExecutable, forKey: "yttExecutable")
            UserDefaults.standard.set(rewriteCommand, forKey: "rewriteCommand")
            UserDefaults.standard.set(outputDirectory, forKey: "outputDirectory")
            model.updateSettings(.defaults)
        }
    }
}

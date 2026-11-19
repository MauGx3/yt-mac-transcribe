import SwiftUI

@main
struct YTTranscribeApp: App {
    @State private var library: LibraryStore
    @State private var model: TranscriptionViewModel

    init() {
        let library = LibraryStore.standard()
        _library = State(initialValue: library)
        _model = State(initialValue: TranscriptionViewModel(settings: .defaults, library: library))
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: model, library: library)
        }
        .windowToolbarStyle(.unified)
        // The review screen opens in its own window so the Library stays usable.
        WindowGroup("Review", id: ReviewWindow.id, for: URL.self) { $reviewFile in
            if let reviewFile {
                ReviewWindow(reviewFile: reviewFile, model: model)
            }
        }
        .defaultSize(width: 860, height: 640)
        Settings {
            SettingsView(model: model)
        }
    }
}

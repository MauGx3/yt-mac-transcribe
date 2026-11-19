// [AI-GENERATED] Claude Code agent; pending human review.
import SwiftUI

/// The screens listed in the sidebar.
enum SidebarItem: String, Hashable, CaseIterable, Identifiable {
    case transcribe
    case library
    case needsReview
    case benchmark

    var id: String { rawValue }

    var title: String {
        switch self {
        case .transcribe: return "Transcribe"
        case .library: return "All Transcripts"
        case .needsReview: return "Needs Review"
        case .benchmark: return "Benchmark"
        }
    }

    var systemImage: String {
        switch self {
        case .transcribe: return "text.badge.plus"
        case .library: return "books.vertical"
        case .needsReview: return "circle.dashed"
        case .benchmark: return "speedometer"
        }
    }
}

/// Main window: a sidebar of screens and the selected screen beside it.
/// With the Tahoe SDK the sidebar and toolbar render as Liquid Glass automatically.
struct RootView: View {
    let model: TranscriptionViewModel
    let library: LibraryStore
    @State private var selection: SidebarItem? = .transcribe

    private var needsReviewCount: Int {
        library.records.filter { $0.reviewStatus == .needsReview }.count
    }

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section {
                    row(.transcribe)
                }
                Section("Library") {
                    row(.library)
                    row(.needsReview)
                        .badge(needsReviewCount)
                }
                Section("Tools") {
                    row(.benchmark)
                }
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 280)
        } detail: {
            detail(for: selection ?? .transcribe)
        }
        .frame(minWidth: 820, minHeight: 540)
    }

    private func row(_ item: SidebarItem) -> some View {
        Label(item.title, systemImage: item.systemImage).tag(item)
    }

    @ViewBuilder
    private func detail(for item: SidebarItem) -> some View {
        switch item {
        case .transcribe:
            ContentView(model: model, showLibrary: { selection = .library })
                .navigationTitle("Transcribe")
        case .library:
            LibraryView(library: library, filter: .all)
                .navigationTitle("All Transcripts")
        case .needsReview:
            LibraryView(library: library, filter: .needsReview)
                .navigationTitle("Needs Review")
        case .benchmark:
            BenchmarkView(model: model)
                .navigationTitle("Benchmark")
        }
    }
}

#Preview {
    RootView(
        model: TranscriptionViewModel(settings: .defaults),
        library: LibraryStore(fileURL: nil)
    )
    .environment(AIRuntimeManager())
}

// [AI-GENERATED] Claude Code agent; pending human review.
//
// The only file that calls Liquid Glass APIs. Views use these helpers instead,
// so macOS 26 gets Liquid Glass and macOS 14 and 15 get the same layout with
// a material background and bordered buttons. CI fails if a glass API shows
// up in any other source file.
//
// `#if compiler(>=6.2)` keeps the app building with Xcode versions older than
// 26, whose SDKs do not have these APIs; those builds always use the fallback.

import AppKit
import SwiftUI

private struct ForceGlassFallbackKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    /// Forces the macOS 14/15 look even where Liquid Glass is available.
    /// Used by previews to show both styles side by side.
    var forceGlassFallback: Bool {
        get { self[ForceGlassFallbackKey.self] }
        set { self[ForceGlassFallbackKey.self] = newValue }
    }
}

extension View {
    /// Liquid Glass in `shape` on macOS 26; a regular material in the same
    /// shape on older systems, or an opaque background with Reduce
    /// Transparency on.
    func appGlass<S: Shape>(in shape: S, tint: Color? = nil, interactive: Bool = false) -> some View {
        modifier(AppGlassModifier(shape: shape, tint: tint, interactive: interactive))
    }

    /// Liquid Glass in a capsule, the system's default glass shape.
    func appGlass(tint: Color? = nil, interactive: Bool = false) -> some View {
        appGlass(in: Capsule(), tint: tint, interactive: interactive)
    }

    /// The one prominent action on a screen, such as Transcribe or Save Reviewed.
    func appPrimaryButtonStyle() -> some View {
        modifier(AppButtonStyleModifier(prominent: true))
    }

    /// Secondary actions that sit on or next to glass.
    func appSecondaryButtonStyle() -> some View {
        modifier(AppButtonStyleModifier(prominent: false))
    }
}

/// Groups floating glass shapes so they render together and can morph into
/// each other on macOS 26. On older systems it only lays out its content.
struct AppGlassContainer<Content: View>: View {
    let spacing: CGFloat?
    let content: Content
    @Environment(\.forceGlassFallback) private var forceFallback

    init(spacing: CGFloat? = nil, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    var body: some View {
        #if compiler(>=6.2)
        if #available(macOS 26, *) {
            if forceFallback {
                content
            } else {
                GlassEffectContainer(spacing: spacing) { content }
            }
        } else {
            content
        }
        #else
        content
        #endif
    }
}

private struct AppGlassModifier<S: Shape>: ViewModifier {
    let shape: S
    let tint: Color?
    let interactive: Bool
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.forceGlassFallback) private var forceFallback

    @ViewBuilder
    func body(content: Content) -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26, *) {
            if forceFallback {
                fallback(content)
            } else {
                content.glassEffect(Glass.regular.tint(tint).interactive(interactive), in: shape)
            }
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }

    @ViewBuilder
    private func fallback(_ content: Content) -> some View {
        if reduceTransparency {
            content
                .background(Color(nsColor: .windowBackgroundColor), in: shape)
                .overlay(shape.stroke(Color.secondary.opacity(0.4)))
        } else {
            content
                .background(tint.map { AnyShapeStyle($0.opacity(0.2)) } ?? AnyShapeStyle(.clear), in: shape)
                .background(.regularMaterial, in: shape)
                .overlay(shape.stroke(Color.primary.opacity(0.08)))
        }
    }
}

private struct AppButtonStyleModifier: ViewModifier {
    let prominent: Bool
    @Environment(\.forceGlassFallback) private var forceFallback

    @ViewBuilder
    func body(content: Content) -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26, *) {
            if forceFallback {
                fallback(content)
            } else if prominent {
                content.buttonStyle(.glassProminent)
            } else {
                content.buttonStyle(.glass)
            }
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }

    @ViewBuilder
    private func fallback(_ content: Content) -> some View {
        if prominent {
            content.buttonStyle(.borderedProminent)
        } else {
            content.buttonStyle(.bordered)
        }
    }
}

// MARK: - Previews

private struct GlassCompatSample: View {
    var body: some View {
        AppGlassContainer(spacing: 12) {
            VStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "link")
                    Text("https://youtu.be/example").foregroundStyle(.secondary)
                    Spacer()
                    Button("Transcribe") {}
                        .appPrimaryButtonStyle()
                }
                .padding(10)
                .appGlass(in: .rect(cornerRadius: 16))
                HStack(spacing: 8) {
                    Button("Previous unsure") {}
                    Button("Next unsure") {}
                }
                .appSecondaryButtonStyle()
                .padding(8)
                .appGlass(tint: .orange)
            }
        }
        .padding(24)
        .frame(width: 420)
        .background(
            LinearGradient(colors: [.blue, .purple, .orange], startPoint: .topLeading, endPoint: .bottomTrailing)
        )
    }
}

#Preview("Glass helpers, both styles") {
    HStack(spacing: 0) {
        GlassCompatSample()
        GlassCompatSample().environment(\.forceGlassFallback, true)
    }
}

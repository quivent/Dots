import SwiftUI

/// Adapted from ~/Complex: calm native surfaces, compact rows, indigo accents.
enum Theme {
    static let codex = Color(red: 0.90, green: 0.38, blue: 0.08)
    static let outgoing = Color(red: 0.16, green: 0.36, blue: 0.78)
    static let incoming = Color(red: 0.40, green: 0.24, blue: 0.66)
    static let accent = Color(UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.43, green: 0.55, blue: 1, alpha: 1)
        : UIColor(red: 0.22, green: 0.35, blue: 0.84, alpha: 1) })
    static let background = Color(.systemBackground)
    static let surface = Color(.secondarySystemBackground)
    static let display = Font.system(.largeTitle, design: .rounded).weight(.bold)
}

struct DotMark: View {
    var size: CGFloat = 64
    var body: some View {
        ZStack {
            Circle().fill(Theme.accent.opacity(0.12))
            Image(systemName: "circle.hexagongrid.fill")
                .font(.system(size: size * 0.53, weight: .medium)).foregroundStyle(Theme.accent)
        }.frame(width: size, height: size).accessibilityHidden(true)
    }
}

struct DotAvatar: View {
    let dot: Dot
    var size: CGFloat = 52
    var body: some View {
        Text(String(dot.name.prefix(1)).uppercased())
            .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(dot.isCodexWorker ? Theme.codex : Theme.accent, in: Circle())
            .overlay(alignment: .bottomTrailing) {
                Circle().fill(dot.isPaused ? Color.orange : Color.green)
                    .frame(width: 12, height: 12).overlay(Circle().stroke(Theme.background, lineWidth: 2))
            }.accessibilityLabel(dot.name + (dot.isPaused ? ", paused" : ""))
    }
}

struct ProminentButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold)).foregroundStyle(.white)
            .frame(maxWidth: .infinity).frame(minHeight: 50)
            .background(Theme.accent.opacity(enabled ? 1 : 0.4), in: RoundedRectangle(cornerRadius: 12))
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

struct InlineError: View {
    let text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.circle")
            .font(.footnote).foregroundStyle(.red).textSelection(.enabled)
    }
}

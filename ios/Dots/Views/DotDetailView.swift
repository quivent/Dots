import SwiftUI

struct DotDetailView: View {
    let dotID: String
    @Environment(DotsStore.self) private var store
    @Environment(\.openURL) private var openURL
    @State private var working = false
    @State private var setup = false
    @State private var showChat = false
    @State private var runtimeAction: String?
    private var dot: Dot? { store.dots.first { $0.id == dotID } }
    var body: some View {
        Group {
            if let dot {
                List {
                    Section {
                        VStack(spacing: 12) {
                            DotAvatar(dot: dot, size: 76)
                            Text(dot.name).font(Theme.display)
                            if !dot.summary.isEmpty { Text(dot.summary).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center) }
                        }.frame(maxWidth: .infinity).padding(.vertical, 18)
                    }.listRowBackground(Color.clear)
                    Section {
                        Label("Dot profile created", systemImage: "checkmark.circle.fill").foregroundStyle(.primary)
                        if dot.roomID != nil {
                            NavigationLink { ChatView(dotID: dot.id) } label: {
                                Label("Open chat", systemImage: "bubble.left.and.bubble.right.fill")
                            }.accessibilityIdentifier("open-chat")
                        } else {
                            Button { setup = true } label: {
                                Label("Finish setup", systemImage: "bubble.left.and.bubble.right")
                            }.accessibilityIdentifier("setup-chat")
                        }
                    } header: { Text("Setup") } footer: {
                        if dot.roomID == nil { Text("Your Dot is saved. Create its conversation whenever you’re ready.") }
                    }
                    Section("Keep up") {
                        NavigationLink { ItemsView(dotID: dot.id, kind: "activity") } label: { Label("Activity", systemImage: "waveform.path") }
                        NavigationLink { ItemsView(dotID: dot.id, kind: "tasks") } label: { Label("Tasks", systemImage: "checklist") }
                    }
                    Section {
                        Button { runtimeAction = dot.isPaused ? "resume" : "pause" } label: {
                            Label(dot.isLocalCodex ? "Stop current turn" : dot.isPaused ? "Resume Dot" : "Pause Dot", systemImage: dot.isPaused ? "play.circle" : "pause.circle")
                        }.disabled(working)
                        if !dot.isLocalCodex { Button { openURL(URL(string: "chatgpt://dots-entry")!) } label: {
                            Label("Manage in ChatGPT", systemImage: "arrow.up.forward.app")
                        } }
                    } footer: {
                        Text(dot.isLocalCodex ? "Stop interrupts the current Codex turn. Child agents, external jobs and Goals have separate controls. Native approvals remain in Codex on your Mac." : "You control Pause and Resume. These change the provider’s main task; delegated jobs and schedules have separate controls. App confirmations cover requests sent here, not autonomous provider activity.")
                    }
                }
                .navigationTitle(dot.name).navigationBarTitleDisplayMode(.inline)
                .navigationDestination(isPresented: $showChat) { ChatView(dotID: dotID) }
                .sheet(isPresented: $setup) {
                    SetupDotSheet(existingID: dotID) { _ in showChat = true }
                }
                .confirmationDialog("\(dot.isLocalCodex ? "Stop current turn in" : runtimeAction == "pause" ? "Pause" : "Resume") \(dot.name)?",
                                    isPresented: Binding(get: { runtimeAction != nil }, set: { if !$0 { runtimeAction = nil } }),
                                    titleVisibility: .visible) {
                    if let action = runtimeAction {
                        Button(dot.isLocalCodex ? "Stop current turn" : action == "pause" ? "Pause Dot" : "Resume Dot") {
                            working = true
                            Task {
                                defer { working = false; runtimeAction = nil }
                                do { try await store.runtime(action, dot: dot) }
                                catch { store.error = error.localizedDescription }
                            }
                        }
                    }
                }
            } else { ContentUnavailableView("Dot unavailable", systemImage: "circle.dashed", description: Text("Refresh your Dots and try again.")) }
        }
    }
}

struct ItemsView: View {
    let dotID: String
    let kind: String
    @Environment(DotsStore.self) private var store
    @State private var items: [ActivityItem] = []
    @State private var loading = true
    @State private var error: String?
    var body: some View {
        Group {
            if loading { ProgressView("Loading…") }
            else if let error {
                ContentUnavailableView {
                    Label("Couldn’t load \(kind)", systemImage: "wifi.exclamationmark")
                } description: { Text(error) } actions: { Button("Try again") { Task { await load() } } }
            } else if items.isEmpty {
                ContentUnavailableView(kind == "tasks" ? "No tasks yet" : "No activity yet", systemImage: kind == "tasks" ? "checklist" : "waveform.path")
            } else {
                List(items) { item in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.title).font(.body.weight(.semibold))
                        if !item.detail.isEmpty { Text(item.detail).font(.subheadline).foregroundStyle(.secondary).textSelection(.enabled) }
                        HStack {
                            if !item.status.isEmpty { Text(item.status.capitalized) }
                            Spacer()
                            if item.date != .distantPast { Text(item.date, style: .relative) }
                        }.font(.caption).foregroundStyle(.tertiary)
                    }.padding(.vertical, 6)
                }.listStyle(.plain)
            }
        }
        .navigationTitle(kind.capitalized).navigationBarTitleDisplayMode(.inline)
        .task { await load() }.refreshable { await load() }
    }
    private func load() async {
        guard let dot = store.dots.first(where: { $0.id == dotID }) else { loading = false; return }
        loading = true; error = nil
        defer { loading = false }
        do { items = try await store.items(dot: dot, kind: kind) }
        catch { self.error = error.localizedDescription }
    }
}

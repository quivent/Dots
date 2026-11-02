import SwiftUI

struct DotsListView: View {
    let chatsOnly: Bool
    var workOnly = false
    @Environment(DotsStore.self) private var store
    @State private var search = ""
    @State private var create = false
    @State private var shared = false
    @State private var ready: Dot?
    private var visible: [Dot] {
        store.dots.filter { $0.isCodexWorker == workOnly && (chatsOnly ? $0.roomID != nil : !$0.humanOnly) && (search.isEmpty || $0.name.localizedCaseInsensitiveContains(search)) }
    }
    var body: some View {
        NavigationStack {
            Group {
                if store.loading && store.dots.isEmpty {
                    ProgressView("Loading your Dots…").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if visible.isEmpty {
                    ContentUnavailableView {
                        Label(search.isEmpty ? (workOnly ? "Your working crew" : chatsOnly ? "No chats yet" : "Meet your next Dot") : "No matches",
                              systemImage: workOnly ? "person.3" : chatsOnly ? "bubble.left.and.bubble.right" : "circle.hexagongrid")
                    } description: {
                        Text(search.isEmpty ? (workOnly ? "Your connected Codex sessions appear here, ready to work with you." : chatsOnly ? "Set up a Dot or finish setting up one you already have." : "Give your Dot a name. Set up its chat when you’re ready.") : "Try another name.")
                    } actions: {
                        if search.isEmpty && !workOnly {
                            Button("Set up a Dot") { create = true }.buttonStyle(.borderedProminent)
                                .accessibilityIdentifier("start-setup")
                        }
                    }
                } else {
                    List {
                        if let syncError = store.catalogSyncError {
                            Text(syncError).font(.caption).foregroundStyle(.secondary)
                        }
                        if store.isDemo {
                            Text("Preview · sample Dots and conversations").font(.caption).foregroundStyle(.secondary)
                                .listRowSeparator(.hidden)
                        }
                        ForEach(visible) { dot in
                            NavigationLink {
                                if chatsOnly { ChatView(dotID: dot.id) } else { DotDetailView(dotID: dot.id) }
                            } label: {
                                HStack(alignment: .top, spacing: 12) {
                                    DotAvatar(dot: dot)
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Text(dot.name).font(.body.weight(.semibold))
                                            Spacer()
                                            if chatsOnly, let date = store.messages[dot.roomID ?? ""]?.last?.date {
                                                Text(date, style: .time).font(.caption).foregroundStyle(.secondary)
                                            }
                                        }
                                        Text(chatsOnly ? (store.messages[dot.roomID ?? ""]?.last?.text ?? (workOnly ? dot.summary : "Continue the conversation")) :
                                                (dot.summary.isEmpty ? "Your ongoing companion" : dot.summary))
                                            .font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                                        if !chatsOnly {
                                            Text(dot.roomID == nil ? "Chat not set up" : (dot.isPaused ? "Paused" : "Chat ready"))
                                                .font(.caption2).foregroundStyle(.tertiary)
                                        }
                                    }
                                }.padding(.vertical, 6)
                            }.accessibilityIdentifier("dot-" + dot.id)
                        }
                    }.listStyle(.plain)
                }
            }
            .background(Theme.background).navigationTitle(workOnly ? "Crew" : chatsOnly ? "Chats" : "Dots")
            .searchable(text: $search, prompt: workOnly ? "Search your crew" : chatsOnly ? "Search chats" : "Search Dots")
            .refreshable { await store.refresh() }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { Task { await store.refresh() } } label: { Image(systemName: "arrow.clockwise") }
                        .accessibilityLabel("Refresh").disabled(store.loading)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if !workOnly {
                    if store.account?.relayURL == DotsStore.hostedRelay {
                        Menu {
                            Button("New chat") { shared = true }
                            if store.account?.hostedOnly != true { Button("Set up a ChatGPT Dot") { create = true } }
                        } label: { Image(systemName: "square.and.pencil") }
                            .accessibilityLabel("New chat or Dot").accessibilityIdentifier("new-dot")
                    } else {
                        Button { create = true } label: { Image(systemName: "square.and.pencil") }
                            .accessibilityLabel("Set up a Dot").accessibilityIdentifier("new-dot")
                    }
                    }
                }
            }
            .sheet(isPresented: $create) { SetupDotSheet { ready = $0 } }
            .sheet(isPresented: $shared) { HostedRoomSheet { ready = $0 } }
            .navigationDestination(item: $ready) { dot in ChatView(dotID: dot.id) }
        }
    }
}


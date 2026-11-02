import SwiftUI

struct RootView: View {
    @Environment(DotsStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    private var syncIdentity: String { "\(scenePhase)|\(store.account?.storageID ?? "signed-out")|\(store.isDemo)" }
    var body: some View {
        Group {
            if store.account != nil || store.isDemo {
                TabView {
                    DotsListView(chatsOnly: true, workOnly: true)
                        .tabItem { Label("Crew", systemImage: "person.3.fill") }
                    DotsListView(chatsOnly: true)
                        .tabItem { Label("Chats", systemImage: "bubble.left.and.bubble.right.fill") }
                    DotsListView(chatsOnly: false)
                        .tabItem { Label("Dots", systemImage: "circle.hexagongrid.fill") }
                    if store.account?.relayURL == DotsStore.hostedRelay {
                        ResearchBankView().tabItem { Label("Bank", systemImage: "books.vertical.fill") }
                    }
                    AccountView().tabItem { Label("Account", systemImage: "person.crop.circle") }
                }
            } else { ConnectView() }
        }
        .task(id: syncIdentity) {
            guard scenePhase == .active, store.account != nil, !store.isDemo else { return }
            while !Task.isCancelled {
                let hosted = store.account?.relayURL == DotsStore.hostedRelay
                if hosted { await store.refreshHostedRooms() }
                else { await store.refresh() }
                do { try await Task.sleep(for: .seconds(hosted ? 2 : 30)) } catch { return }
            }
        }
        .alert("Couldn’t complete the request", isPresented: Binding(
            get: { store.error != nil }, set: { if !$0 { store.error = nil } }
        )) { Button("OK") { store.error = nil } } message: { Text(store.error ?? "") }
    }
}

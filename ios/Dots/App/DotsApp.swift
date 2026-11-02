import SwiftUI

@main
struct DotsApp: App {
    @State private var store = DotsStore()
    var body: some Scene {
        WindowGroup {
            RootView().environment(store).tint(Theme.accent)
                .task {
                    #if DEBUG
                    if CommandLine.arguments.contains("-demo") {
                        store.seedDemo()
                        if CommandLine.arguments.contains("-demo-empty") { store.dots = []; store.messages = [:] }
                        if CommandLine.arguments.contains("-demo-no-chats") {
                            store.dots = store.dots.map { var dot = $0; dot.roomID = nil; return dot }
                            store.messages = [:]
                        }
                        return
                    }
                    if CommandLine.arguments.contains("-signed-out") { store.disconnect(); return }
                    #endif
                    await store.refresh()
                }
        }
    }
}

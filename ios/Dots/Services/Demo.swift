import Foundation

enum Demo {
    static func items(kind: String) -> [ActivityItem] {
        (kind == "tasks" ? [
            ["id": "one", "title": "Review the iOS build", "summary": "Check the setup flow and conversation handoff.", "status": "in progress"],
            ["id": "two", "title": "Collect this week’s notes", "summary": "Ready for your review.", "status": "completed"]
        ] : [
            ["id": "one", "title": "A quieter morning", "summary": "Your priorities are ready. There are two decisions to review.", "status": "Update"],
            ["id": "two", "title": "Project notes organized", "summary": "Collected the open questions for the next conversation.", "status": "Completed"]
        ]).enumerated().map { ActivityItem(json: $0.element.merging(["created_at": Date.now.addingTimeInterval(Double(-$0.offset * 3600)).timeIntervalSince1970]) { _, b in b }, index: $0.offset) }
    }
}

extension DotsStore {
    func seedDemo() {
        // An explicit preview, never persisted or connected to a real account.
        isDemo = true; account = nil; error = nil; uncertainCreation = false
        pending = [:]; messages = [:]; olderCursors = [:]; sending = []; loading = false
        contextUsage = [:]; activeTasks = [:]
        waitingForReply = [:]; chatErrors = [:]; historyReadSeconds = [:]
        dots = [
            Dot(id: "atlas", name: "Atlas", summary: "Projects, plans, and the things worth following up.", roomID: "atlas-room"),
            Dot(id: "sage", name: "Sage", summary: "A little space to think things through.", roomID: "sage-room"),
            Dot(id: "scout", name: "Scout", summary: "Your next Dot. Set up a chat when you’re ready.")
        ]
        messages["atlas-room"] = [
            .init(id: "a", text: "Let’s keep the iOS app simple. Set up the Dot first, then start a conversation.", isMine: true, date: .now.addingTimeInterval(-1800)),
            .init(id: "b", text: "That makes sense. The Dot is the ongoing relationship; the chat is where we work together.\n\nI’ll keep setup separate so you can come back to it whenever you’re ready.", isMine: false, date: .now.addingTimeInterval(-1740)),
            .init(id: "c", text: "What would you like us to focus on first?\n\nYou can also read the [OpenAI documentation](https://learn.chatgpt.com/docs/dots).", isMine: false, date: .now.addingTimeInterval(-1700))
        ]
        messages["sage-room"] = [.init(id: "s", text: "We can pick up wherever you’d like.", isMine: false, date: .now.addingTimeInterval(-3600))]
    }
}

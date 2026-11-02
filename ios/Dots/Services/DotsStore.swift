import Foundation
import Observation

@MainActor @Observable
final class DotsStore {
    var account: AccountSession?
    var dots: [Dot] = []
    var messages: [String: [ChatMessage]] = [:]
    var olderCursors: [String: String] = [:]
    var contextUsage: [String: ContextUsage] = [:]
    var activeTasks: [String: [ActivityItem]] = [:]
    var quietMembers: [String: [String]] = [:]
    var pending: [String: PendingMessage] = [:]
    var error: String?
    var loading = false
    var sending = Set<String>()
    var waitingForReply: [String: Date] = [:]
    var chatErrors: [String: String] = [:]
    var historyReadSeconds: [String: Double] = [:]
    private var readingHistory = Set<String>()
    private var loadedOlderRooms = Set<String>()
    var uncertainCreation = false
    var isDemo = false
    let api: DotsAPI
    private var generation = UUID()
    private var readingHostedRooms = false
    private var hostedCatalogRevision = 0
    private var creatingDot = false
    var catalogSyncError: String?

    private func clearChatStatus() {
        readingHostedRooms = false; hostedCatalogRevision += 1; catalogSyncError = nil
        quietMembers = [:]
        waitingForReply = [:]; chatErrors = [:]; historyReadSeconds = [:]
        readingHistory = []; loadedOlderRooms = []
    }

    init(api: DotsAPI = DotsAPI()) {
        self.api = api
        if let text = Keychain.read("session"), let data = text.data(using: .utf8),
           let saved = try? JSONDecoder().decode(AccountSession.self, from: data), saved.isValid {
            account = saved
            restorePending(saved)
        }
    }

    private func restorePending(_ account: AccountSession) {
        if let text = Keychain.read("pending-" + account.storageID), let data = text.data(using: .utf8),
           let saved = try? JSONDecoder().decode([String: PendingMessage].self, from: data) { pending = saved }
        uncertainCreation = Keychain.read("creation-" + account.storageID) != nil
    }

    private func savePending() throws {
        guard let account else { throw APIError.invalidSession }
        try Keychain.write(String(decoding: JSONEncoder().encode(pending), as: UTF8.self), account: "pending-" + account.storageID)
    }

    func connect(_ session: AccountSession) async throws {
        guard session.isValid else { throw APIError.invalidSession }
        let attempt = generation
        let catalog = try await api.dots(account: session)
        guard generation == attempt else { throw CancellationError() }
        try Keychain.write(String(decoding: JSONEncoder().encode(session), as: UTF8.self), account: "session")
        generation = UUID(); clearChatStatus(); account = session; dots = catalog; error = nil; isDemo = false
        messages = [:]; olderCursors = [:]; pending = [:]; contextUsage = [:]; activeTasks = [:]
        restorePending(session)
    }

    func disconnect() {
        generation = UUID()
        clearChatStatus()
        if let account {
            Keychain.delete("pending-" + account.storageID)
            Keychain.delete("creation-" + account.storageID)
        }
        Keychain.delete("session")
        account = nil; dots = []; messages = [:]; pending = [:]; olderCursors = [:]; contextUsage = [:]; activeTasks = [:]
        error = nil; isDemo = false; uncertainCreation = false; loading = false; sending = []
    }

    func connectPairedMac(_ session: AccountSession) async throws {
        guard session.isValid, session.relayURL != nil || session.bluetoothID != nil else { throw APIError.invalidSession }
        try Keychain.write(String(decoding: JSONEncoder().encode(session), as: UTF8.self), account: "session")
        generation = UUID(); clearChatStatus(); account = session; dots = []; messages = [:]; pending = [:]; olderCursors = [:]; contextUsage = [:]; activeTasks = [:]
        error = nil; loading = false; isDemo = false
        restorePending(session)
        await refresh()
    }

    static let hostedRelay = "https://dots.kosmos.institute"

    func connectHostedRelay() async throws {
        guard !isDemo, let current = account,
              current.bluetoothID != nil || current.relayURL != nil else { throw APIError.invalidSession }
        guard !loading, sending.isEmpty, pending.isEmpty, !uncertainCreation, !creatingDot else { throw APIError.connectionBusy }
        let candidate = AccountSession(accessToken: current.accessToken, accountID: current.accountID,
                                       relayURL: Self.hostedRelay, macName: current.macName)
        // This credential belongs to the paired phone, never the provider login.
        // A failed HTTPS check leaves the working Bluetooth/network session intact.
        try await connect(candidate)
    }

    func refresh() async {
        guard !isDemo, let account, !loading else { return }
        let attempt = generation
        let revision = hostedCatalogRevision
        loading = true
        defer { if generation == attempt { loading = false } }
        do {
            let catalog = try await api.dots(account: account)
            guard generation == attempt else { return }
            if account.relayURL == Self.hostedRelay && hostedCatalogRevision != revision {
                dots = dots.filter(\.isHosted) + catalog.filter { !$0.isHosted }
            } else { dots = catalog }
            error = nil
        } catch {
            if !Task.isCancelled, generation == attempt { self.error = error.localizedDescription }
        }
    }

    func refreshHostedRooms() async {
        guard !isDemo, let account, account.relayURL == Self.hostedRelay, !readingHostedRooms else { return }
        let attempt = generation
        let revision = hostedCatalogRevision
        readingHostedRooms = true
        defer { if generation == attempt { readingHostedRooms = false } }
        do {
            let rows = try await api.collection("/hosted/rooms", account: account)
            let rooms = try rows.map(Dot.init(json:))
            guard !Task.isCancelled, generation == attempt, hostedCatalogRevision == revision else { return }
            // This snapshot is independent of the Mac/provider catalog. Keep
            // provider Dots, drafts, open chats and pending sends intact.
            dots = rooms + dots.filter { !$0.isHosted }
            hostedCatalogRevision += 1; catalogSyncError = nil
        } catch {
            if !Task.isCancelled, generation == attempt {
                catalogSyncError = "Couldn’t update chats. Retrying…"
            }
        }
    }

    func create(name: String) async throws -> Dot {
        guard !uncertainCreation else { throw APIError.deliveryUnknown }
        guard !creatingDot else { throw APIError.connectionBusy }
        creatingDot = true
        defer { creatingDot = false }
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 80 else { throw APIError.invalidResponse }
        if isDemo {
            let dot = Dot(id: UUID().uuidString, name: trimmed, summary: "Ready to set up a conversation")
            dots.insert(dot, at: 0); return dot
        }
        guard let account else { throw APIError.invalidSession }
        let attempt = generation
        // Use a fresh account catalog, not the mixed and possibly stale visible
        // list. Hosted agents and shared chats do not make this an additional Dot.
        let additional = try await api.creationIsAdditional(account: account)
        guard generation == attempt else { throw CancellationError() }
        // Record before the write so an interrupted process cannot silently create twice.
        try Keychain.write(trimmed, account: "creation-" + account.storageID)
        uncertainCreation = true
        do {
            let dot = try await api.createProfile(name: trimmed, additional: additional, account: account)
            guard generation == attempt else { throw CancellationError() }
            Keychain.delete("creation-" + account.storageID)
            uncertainCreation = false; dots.insert(dot, at: 0)
            return dot
        } catch {
            if generation == attempt, let failure = error as? APIError, !failure.isUnknown {
                Keychain.delete("creation-" + account.storageID); uncertainCreation = false
            }
            throw error
        }
    }

    func acknowledgeCreationReview() {
        if let account { Keychain.delete("creation-" + account.storageID) }
        uncertainCreation = false
    }

    func createChat(dot: Dot) async throws -> Dot {
        if isDemo {
            var updated = dot; updated.roomID = "demo-" + dot.id
            replace(updated); return updated
        }
        guard let account else { throw APIError.invalidSession }
        let attempt = generation
        // Re-read before writing to recover a previous room creation with a lost response.
        let current = try await api.profile(dot.id, account: account)
        let updated = try await api.createChat(for: current, account: account)
        guard generation == attempt else { throw CancellationError() }
        replace(updated); return updated
    }

    private func replace(_ dot: Dot) {
        if let index = dots.firstIndex(where: { $0.id == dot.id }) { dots[index] = dot }
    }

    func loadMessages(_ room: String, older: Bool = false) async {
        guard !isDemo, let account else { return }
        guard !readingHistory.contains(room) else { return }
        readingHistory.insert(room)
        let attempt = generation
        let started = ContinuousClock.now
        defer { if generation == attempt { readingHistory.remove(room) } }
        do {
            let page = try await api.messages(room: room, before: older ? olderCursors[room] : nil, account: account)
            guard generation == attempt else { return }
            var byID = Dictionary((messages[room] ?? []).map { ($0.id, $0) }, uniquingKeysWith: { _, b in b })
            for message in page.messages { byID[message.id] = message }
            messages[room] = byID.values.sorted { $0.date < $1.date }
            if let outstanding = pending[room], page.messages.contains(where: { $0.requestID == outstanding.id }) {
                pending[room] = nil
                try savePending()
            }
            if older || !loadedOlderRooms.contains(room) { olderCursors[room] = page.before }
            if older { loadedOlderRooms.insert(room) }
            if !older { contextUsage[room] = page.context }
            if let since = waitingForReply[room], page.messages.contains(where: { !$0.isMine && $0.date >= since }) {
                waitingForReply[room] = nil
            }
            let duration = started.duration(to: .now).components
            historyReadSeconds[room] = Double(duration.seconds) + Double(duration.attoseconds) / 1e18
            chatErrors[room] = nil
        } catch { if generation == attempt { chatErrors[room] = error.localizedDescription } }
    }

    @discardableResult
    func enqueue(_ text: String, room: String, approveWork: Bool = false) -> Bool {
        if dots.first(where: { $0.roomID == room })?.isPaused == true {
            error = APIError.dotPaused.localizedDescription
            return false
        }
        guard pending[room] == nil, !sending.contains(room) else { return false }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 12000 else { return false }
        guard dots.first(where: { $0.roomID == room })?.humanOnly == true || !contextBudget(room).wouldEnterReserve(adding: trimmed) else {
            error = APIError.contextBufferReached.localizedDescription; return false
        }
        let work = requiresApproval(trimmed, room: room)
        guard !work || approveWork else { error = APIError.workApprovalRequired.localizedDescription; return false }
        pending[room] = PendingMessage(id: UUID().uuidString, roomID: room, text: trimmed, createdAt: .now, workApproved: work && approveWork)
        if !isDemo {
            do { try savePending() }
            catch { pending[room] = nil; self.error = error.localizedDescription; return false }
        }
        return true
    }

    func send(_ text: String, room: String) async {
        guard enqueue(text, room: room) else { return }
        await retryMessage(room)
    }

    func approvePendingWork(_ id: String, room: String) -> Bool {
        guard let original = pending[room], original.id == id else { return false }
        var approved = original; approved.workApproved = true; pending[room] = approved
        if !isDemo {
            do { try savePending() }
            catch { pending[room] = original; self.error = error.localizedDescription; return false }
        }
        return true
    }

    func retryMessage(_ room: String) async {
        guard let message = pending[room], !sending.contains(room) else { return }
        guard dots.first(where: { $0.roomID == room })?.isPaused != true else {
            error = APIError.dotPaused.localizedDescription
            return
        }
        guard !requiresApproval(message.text, room: room) || message.workApproved == true else {
            error = APIError.workApprovalRequired.localizedDescription
            return
        }
        // Keep unconfirmed writes for reconciliation; never retry into the reserve.
        guard dots.first(where: { $0.roomID == room })?.humanOnly == true || !contextBudget(room).wouldEnterReserve(adding: message.text) else {
            error = APIError.contextBufferReached.localizedDescription; return
        }
        if isDemo {
            messages[room, default: []].append(.init(id: message.id, text: message.text, isMine: true, date: .now))
            pending[room] = nil; return
        }
        guard let account else { return }
        let attempt = generation
        sending.insert(room)
        defer { if generation == attempt { sending.remove(room) } }
        do {
            let id = try await api.send(message, account: account)
            guard generation == attempt else { return }
            messages[room, default: []].append(.init(id: id, text: message.text, isMine: true, date: .now))
            pending[room] = nil
            try savePending()
            if dots.first(where: { $0.roomID == room })?.humanOnly != true { waitingForReply[room] = message.createdAt ?? .now }
            await loadMessages(room)
        } catch { if generation == attempt { self.error = error.localizedDescription } }
    }

    func contextBudget(_ room: String) -> ContextBudget {
        ContextBudget(reported: contextUsage[room], messages: messages[room] ?? [])
    }

    func requiresApproval(_ text: String, room: String) -> Bool {
        if dots.first(where: { $0.roomID == room })?.humanOnly == true { return false }
        return room.hasPrefix("hub-") || room.hasPrefix("mac-codex-") || WorkNotice.assess(text).requiresApproval
    }

    func createHostedRoom(name: String, members: [String], requestID: String, people: [String]? = nil) async throws -> Dot {
        guard let account else { throw APIError.invalidSession }
        let attempt = generation
        var body: [String: Any] = ["name": name, "members": members, "request_id": requestID]
        if let people { body["people"] = people }
        let result = try await api.request("POST", "/hosted/rooms", account: account, body: body)
        guard generation == attempt else { throw CancellationError() }
        let dot = try Dot(json: result)
        if !dots.contains(where: { $0.id == dot.id }) { dots.insert(dot, at: 0) }
        hostedCatalogRevision += 1
        return dot
    }

    func items(dot: Dot, kind: String) async throws -> [ActivityItem] {
        if isDemo { return Demo.items(kind: kind) }
        guard let account, ["activity", "tasks"].contains(kind) else { throw APIError.invalidSession }
        let attempt = generation
        let rows = try await api.collection("/tbo/" + DotsAPI.segment(dot.id) + "/" + kind, account: account, key: "data")
        guard generation == attempt else { throw CancellationError() }
        return rows.enumerated().map { ActivityItem(json: $0.element, index: $0.offset) }
    }

    func exportConversation(room: String, dotID: String) async throws -> String {
        let name = dots.first(where: { $0.id == dotID })?.name ?? "Dot"
        var collected = messages[room] ?? []
        if !isDemo {
            guard let account else { throw APIError.invalidSession }
            let attempt = generation
            collected = []
            var before: String?, seen = Set<String>(), complete = false, bytes = 0
            for _ in 0..<1000 {
                let page = try await api.messages(room: room, before: before, account: account)
                guard generation == attempt else { throw CancellationError() }
                collected += page.messages
                bytes += page.messages.reduce(0, { $0 + $1.text.utf8.count })
                guard bytes < 20_000_000 else { throw APIError.invalidResponse }
                guard let cursor = page.before else { complete = true; break }
                guard seen.insert(cursor).inserted else { throw APIError.invalidResponse }
                before = cursor
            }
            guard complete else { throw APIError.invalidResponse }
        }
        let unique = Dictionary(collected.map { ($0.id, $0) }, uniquingKeysWith: { _, b in b }).values.sorted { $0.date < $1.date }
        return "Conversation with \(name)\nSaved \(Date.now.ISO8601Format())\n\n" + unique.map {
            ($0.isMine ? "You" : name) + " · " + $0.date.ISO8601Format() + "\n" + $0.text
        }.joined(separator: "\n\n")
    }

    func loadTaskAwareness(dotID: String) async {
        guard let dot = dots.first(where: { $0.id == dotID }) else { return }
        let attempt = generation
        if let tasks = try? await items(dot: dot, kind: "tasks"), generation == attempt {
            activeTasks[dotID] = tasks.filter(\.isActive)
            if let requestID = tasks.first?.requestID {
                quietMembers[dotID] = tasks.prefix(while: { $0.requestID == requestID }).filter { $0.replyOutcome == "quiet" }.map(\.title)
            } else { quietMembers[dotID] = [] }
        }
    }

    func runtime(_ action: String, dot: Dot) async throws {
        guard ["pause", "resume"].contains(action) else { throw APIError.invalidResponse }
        if !isDemo {
            guard let account else { throw APIError.invalidSession }
            let attempt = generation
            _ = try await api.request("POST", "/tbo/" + DotsAPI.segment(dot.id) + "/runtime/" + action, account: account)
            let current = try await api.profile(dot.id, account: account)
            guard generation == attempt else { throw CancellationError() }
            replace(current)
            if !dot.isLocalCodex { guard current.isPaused == (action == "pause") else { throw APIError.invalidResponse } }
            return
        }
        var updated = dot; updated.isPaused = action == "pause"; replace(updated)
    }
}

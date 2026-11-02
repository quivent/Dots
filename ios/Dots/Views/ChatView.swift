import SwiftUI

struct ChatView: View {
    let dotID: String
    @Environment(DotsStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var draft = ""
    @State private var nearBottom = true
    @State private var hasPositioned = false
    @State private var showContext = false
    @State private var scrollRevision = 0
    @State private var workRequest = ""
    @State private var workRequestID: String?
    @State private var showWorkApproval = false
    @State private var runtimeAction: String?
    @State private var changingRuntime = false
    @State private var approvals: [HostedApproval] = []
    @State private var reviewingApproval: HostedApproval?
    @FocusState private var composerFocused: Bool
    private var dot: Dot? { store.dots.first { $0.id == dotID } }
    private var room: String? { dot?.roomID }
    private var messages: [ChatMessage] { store.messages[room ?? ""] ?? [] }
    var body: some View {
        VStack(spacing: 0) {
            if dot?.isPaused == true {
                HStack {
                    Label("Paused on provider", systemImage: "pause.circle.fill")
                    Spacer()
                    Button("Resume") { runtimeAction = "resume" }.disabled(changingRuntime)
                }.font(.caption).foregroundStyle(.orange).padding(.horizontal, 16).padding(.vertical, 8)
            }
            if let room, dot?.humanOnly != true {
                ContextMeter(budget: store.contextBudget(room), draft: draft) { showContext = true }
            }
            if dot?.humanOnly == true { Text((dot?.peopleNames ?? []).joined(separator: " · ")).font(.caption).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.vertical, 4) }
            ForEach(approvals) { approval in
                Button { reviewingApproval = approval } label: {
                    Label(approval.agent + " needs approval · review operation", systemImage: "hand.raised.fill")
                        .font(.subheadline).foregroundStyle(.orange).padding(10)
                }
            }
            if store.isDemo {
                Text("Preview conversation").font(.caption2).foregroundStyle(.secondary).padding(.vertical, 5)
            }
            if let tasks = store.activeTasks[dotID], !tasks.isEmpty {
                Button { showContext = true } label: {
                    Label("\(tasks.count) active task\(tasks.count == 1 ? "" : "s")", systemImage: "checklist")
                        .font(.caption).foregroundStyle(.orange).padding(.horizontal, 16).padding(.bottom, 6)
                }
            }
            if let quiet = store.quietMembers[dotID], !quiet.isEmpty {
                Text(quiet.joined(separator: ", ") + " listened quietly")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.bottom, 6)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if let room, store.olderCursors[room] != nil {
                            Button("Load earlier messages") { Task { await store.loadMessages(room, older: true) } }.font(.caption)
                        }
                        if messages.isEmpty {
                            VStack(spacing: 14) {
                                DotMark(size: 52)
                                Text("Start with what matters.").font(.title3.weight(.semibold))
                                Text(dot?.humanOnly == true ? "Send a message to start your conversation." : "Tell \(dot?.name ?? "your Dot") what you’d like to work on together.")
                                    .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                            }.frame(maxWidth: .infinity).padding(.vertical, 70)
                        }
                        ForEach(messages) { message in MessageBubble(message: message) }
                        if let room, let pending = store.pending[room] {
                            VStack(alignment: .trailing, spacing: 8) {
                                MessageBubble(message: .init(id: pending.id, text: pending.text, isMine: true, date: .now))
                                if store.sending.contains(room) {
                                    Label("Sending…", systemImage: "clock").font(.caption).foregroundStyle(.secondary)
                                } else {
                                    Text("Delivery not confirmed. Check the conversation before retrying.")
                                        .font(.caption).foregroundStyle(.secondary)
                                    HStack {
                                        Button("Check delivery") { Task { await store.loadMessages(room) } }
                                        Button("Retry same message") {
                                            if store.requiresApproval(pending.text, room: room) && pending.workApproved != true {
                                                workRequest = pending.text; workRequestID = pending.id; showWorkApproval = true
                                            } else { Task { await store.retryMessage(room) } }
                                        }
                                    }.font(.caption)
                                }
                            }
                        }
                        if let room, let since = store.waitingForReply[room] {
                            TimelineView(.periodic(from: since, by: 1)) { tick in
                                HStack(spacing: 8) {
                                    ProgressView().controlSize(.small)
                                    Text("Waiting for " + (dot?.name ?? "your Dot") + " · " + String(max(0, Int(tick.date.timeIntervalSince(since)))) + "s")
                                        .font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                }.padding(.vertical, 8)
                            }.accessibilityIdentifier("waiting-for-reply")
                        }
                        Color.clear.frame(height: 8).id("bottom")
                            .onAppear { nearBottom = true }.onDisappear { nearBottom = false }
                    }.padding(.horizontal, 16).padding(.top, 12)
                }
                .defaultScrollAnchor(.bottom)
                .scrollDismissesKeyboard(.interactively)
                .refreshable { if let room { await store.loadMessages(room) } }
                .onChange(of: messages.last?.id) { _, _ in
                    // Do not pull readers away from older messages during polling.
                    if nearBottom || messages.last?.isMine == true || !hasPositioned {
                        hasPositioned = true
                        scrollRevision += 1
                    }
                }
                .onChange(of: room.flatMap { store.pending[$0]?.id }) { _, id in
                    if id != nil { scrollRevision += 1 }
                }
                .onChange(of: composerFocused) { _, focused in
                    if focused { scrollRevision += 1 }
                }
                .onAppear { scrollRevision += 1 }
                .task(id: scrollRevision) {
                    // Let the new bubble and keyboard inset lay out before scrolling.
                    do { try await Task.sleep(for: .milliseconds(120)) } catch { return }
                    withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("bottom", anchor: .bottom) }
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { composer }
        .background(Theme.background).navigationTitle(dot?.name ?? "Chat").navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .sheet(isPresented: $showContext) { if let room { ContextPanel(dotID: dotID, room: room) } }
        .sheet(item: $reviewingApproval) { approval in
            HostedApprovalSheet(approval: approval) { accept in
                guard let account = store.account else { throw APIError.invalidSession }
                _ = try await store.api.request("POST", "/hosted/approvals/" + DotsAPI.segment(approval.id), account: account, body: ["accept": accept])
                await loadApprovals()
            }
        }
        .sheet(isPresented: $showWorkApproval) {
            let requested = workRequest
            let requestID = workRequestID
            WorkRequestApproval(text: requested, memberNames: dot?.isHosted == true ? dot?.memberNames ?? [] : [], isLocalCodex: dot?.isLocalCodex == true) {
                if let requestID, let room {
                    if store.approvePendingWork(requestID, room: room) { Task { await store.retryMessage(room) } }
                } else { queueMessage(requested, approveWork: true) }
            }
        }
        .alert(dot?.isLocalCodex == true ? "Stop the current Codex turn?" : runtimeAction == "resume" ? "Resume your Dot?" : "Pause your Dot?", isPresented: Binding(
            get: { runtimeAction != nil }, set: { if !$0 { runtimeAction = nil } }
        )) {
            Button("Cancel", role: .cancel) { runtimeAction = nil }
            if let action = runtimeAction, let dot {
                Button(dot.isLocalCodex ? "Stop current turn" : action == "resume" ? "Resume Dot" : "Pause Dot") {
                    runtimeAction = nil; changingRuntime = true
                    Task {
                        defer { changingRuntime = false }
                        do { try await store.runtime(action, dot: dot) }
                        catch { store.error = error.localizedDescription }
                    }
                }.accessibilityIdentifier("confirm-runtime-change")
            }
        } message: {
            Text(dot?.isLocalCodex == true ? "Interrupts this session’s current turn. Child agents and external jobs have separate controls. Sending another message continues this session." : runtimeAction == "resume"
                 ? "The provider resumes its main task. The app cannot intercept autonomous cloud activity. Work confirmations apply to requests sent here."
                 : "Stops the provider’s current main task. Delegated jobs and schedules have separate controls.")
        }
        .toolbar { ToolbarItem(placement: .topBarTrailing) {
            if dot?.humanOnly != true {
            Button {
                runtimeAction = dot?.isPaused == true ? "resume" : "pause"
            } label: {
                Image(systemName: dot?.isPaused == true ? "play.circle" : "pause.circle")
            }.accessibilityLabel(dot?.isLocalCodex == true ? "Stop current turn" : dot?.isPaused == true ? "Resume Dot" : "Pause Dot")
                .accessibilityIdentifier("runtime-control").disabled(changingRuntime)
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            if dot?.humanOnly != true {
            NavigationLink { DotDetailView(dotID: dotID) } label: { Image(systemName: "info.circle") }.accessibilityLabel("Dot details")
            }
        } }
        .task(id: scenePhase) {
            guard scenePhase == .active, let room else { return }
            await store.loadMessages(room)
            if dot?.humanOnly != true {
                await loadApprovals()
                Task { await store.loadTaskAwareness(dotID: dotID) }
            }
            var polls = 0
            while !Task.isCancelled {
                do { try await Task.sleep(for: .milliseconds(store.waitingForReply[room] != nil ? 1_000 : 2_000)) } catch { return }
                guard !Task.isCancelled else { return }
                await store.loadMessages(room)
                if dot?.isHosted == true && dot?.humanOnly != true { await loadApprovals() }
                polls += 1
                if dot?.humanOnly != true && polls % (dot?.isHosted == true ? 2 : 15) == 0 { Task { await store.loadTaskAwareness(dotID: dotID) } }
            }
        }
    }
    private var composer: some View {
        VStack(spacing: 7) {
            if let room, let error = store.chatErrors[room] {
                HStack {
                    Text(error).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Retry") { Task { await store.loadMessages(room) } }.font(.caption.weight(.semibold))
                }.padding(.horizontal, 18)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("Message \(dot?.name ?? "your Dot")", text: $draft, axis: .vertical)
                    .lineLimit(1...6).padding(.leading, 16).padding(.vertical, 12)
                    .focused($composerFocused)
                    .accessibilityIdentifier("message-draft")
                Button {
                    if let room, store.requiresApproval(draft, room: room) {
                        workRequest = draft; workRequestID = nil; composerFocused = false; showWorkApproval = true
                    } else { queueMessage(draft) }
                } label: {
                    Image(systemName: "arrow.up").font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(.white).frame(width: 38, height: 38)
                        .background(canSend ? Theme.outgoing : Color(.systemGray3), in: Circle())
                }.disabled(!canSend).accessibilityLabel("Send message").padding(5)
            }
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 26))
            .overlay(RoundedRectangle(cornerRadius: 26).stroke(.primary.opacity(0.06), lineWidth: 1))
            .padding(.horizontal, 12)
        }.padding(.top, 8).padding(.bottom, 8).background(.bar)
    }
    private func queueMessage(_ text: String, approveWork: Bool = false) {
        guard let room else { return }
        withAnimation(.easeOut(duration: 0.2)) {
            if store.enqueue(text, room: room, approveWork: approveWork) {
                if draft == text { draft = "" }
                Task { await store.retryMessage(room) }
            }
        }
    }
    private func loadApprovals() async {
        guard dot?.isHosted == true, let room, let account = store.account else { return }
        do {
            let result = try await store.api.request("GET", "/hosted/rooms/" + DotsAPI.segment(room) + "/approvals", account: account)
            approvals = (result["items"] as? [[String: Any]] ?? []).compactMap {
                guard let id = $0["id"] as? String, let agent = $0["agent"] as? String, let details = $0["details"] as? String else { return nil }
                return HostedApproval(id: id, agent: agent, details: details)
            }
        } catch { /* Chat delivery errors are displayed by the regular history poll. */ }
    }
    private var canSend: Bool {
        guard let room else { return false }
        return dot?.isPaused != true && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.count <= 12000
            && store.pending[room] == nil && !store.sending.contains(room)
            && (dot?.humanOnly == true || !store.contextBudget(room).wouldEnterReserve(adding: draft))
    }
}

private struct WorkRequestApproval: View {
    let text: String
    var memberNames: [String] = []
    var isLocalCodex = false
    var onApprove: () -> Void
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Label("Review your message", systemImage: "paperplane")
                        .font(.headline)
                    if isLocalCodex {
                        Text("Your message goes directly to the existing Mac session. It steers the current turn if Codex is working, or starts a turn if idle. The session keeps its instructions, tools and permissions. Native approvals and questions remain in Codex on the Mac.")
                            .font(.subheadline)
                    }
                    if !memberNames.isEmpty {
                        Text((memberNames.count > 1 ? "Listening members: " : "Responding members: ") + memberNames.joined(separator: ", ")).font(.headline)
                        Text(memberNames.count > 1 ? "Members respond only when relevant and do not automatically reply to each other." : "Sends your message to this Codex session.")
                            .font(.subheadline)
                    }
                    Text(text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        .padding().background(Theme.surface, in: RoundedRectangle(cornerRadius: 16))
                    Text("Approval applies to this request. It does not authorize unrelated future jobs. The provider does not expose a hard gate for all autonomous activity to this app.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(20)
            }.navigationTitle("Approve work request").navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                Button("Approve and send") { dismiss(); onApprove() }
                    .buttonStyle(ProminentButtonStyle()).padding(16).background(.bar)
                    .accessibilityIdentifier("approve-work-request")
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }
}

struct MessageBubble: View {
    let message: ChatMessage
    var body: some View {
        HStack {
            if message.isMine { Spacer(minLength: 48) }
            VStack(alignment: .leading, spacing: 5) {
                if let name = message.senderName { Text(name).font(.caption.weight(.semibold)) }
                Text(MessageFormatting.attributed(message.text)).textSelection(.enabled).font(.body)
            }
                .tint(.white)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .foregroundStyle(.white)
                .background(message.isMine ? Theme.outgoing : Theme.incoming, in: RoundedRectangle(cornerRadius: 18))
                .accessibilityIdentifier("bubble-" + message.id)
                .accessibilityLabel((message.isMine ? "You: " : "Dot: ") + String(MessageFormatting.attributed(message.text).characters))
            if !message.isMine { Spacer(minLength: 48) }
        }
    }
}

import SwiftUI
import UniformTypeIdentifiers

struct ContextMeter: View {
    let budget: ContextBudget
    var draft = ""
    var showDetails: () -> Void
    private var blocked: Bool { budget.bufferReached || (!draft.isEmpty && budget.wouldEnterReserve(adding: draft)) }
    private var color: Color { blocked ? .red : budget.fraction >= 0.8 ? .orange : Theme.incoming }
    private func compact(_ count: Int) -> String {
        if count == 1_000_000 { return "1M" }
        if count >= 10_000 { return (Double(count) / 1_000).formatted(.number.precision(.fractionLength(0...1))) + "K" }
        return count.formatted()
    }
    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("Context").font(.subheadline.weight(.semibold))
                    Spacer(minLength: 8)
                    Text((budget.isEstimated ? "~" : "") + compact(budget.used) + " / " + compact(budget.limit))
                        .font(.subheadline.weight(.semibold).monospacedDigit())
                }.foregroundStyle(.primary)
                GeometryReader { geometry in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color(.systemGray4))
                        Rectangle().fill(Color.orange.opacity(0.45))
                            .frame(width: geometry.size.width * 0.1)
                            .offset(x: geometry.size.width * 0.9)
                        Rectangle().fill(color).frame(width: geometry.size.width * budget.fraction)
                        Rectangle().fill(Color.primary.opacity(0.75)).frame(width: 2)
                            .offset(x: geometry.size.width * 0.9 - 1)
                    }.clipShape(Capsule())
                }.frame(height: 10).accessibilityHidden(true)
                ViewThatFits(in: .horizontal) {
                    HStack {
                        Text(blocked ? "Buffer reached · save chat" : budget.isEstimated ? "Estimate · full usage unknown" : "Reported usage")
                        Spacer(minLength: 8)
                        Text(compact(budget.reserve) + " reserved")
                    }
                    Text(blocked ? "Buffer reached · save chat" : budget.isEstimated ? "Estimate · full usage unknown · 10% reserve" : "Reported usage · 10% reserve")
                }.font(.caption).foregroundStyle(blocked ? Color.red : Color.primary)
            }.accessibilityElement(children: .combine)
                .accessibilityIdentifier("context-usage")
            Button(action: showDetails) {
                Image(systemName: "ellipsis.circle").font(.title3)
                    .foregroundStyle(.primary).frame(width: 44, height: 44)
            }.buttonStyle(.plain).accessibilityLabel("Context details and save conversation")
                .accessibilityIdentifier("context-details")
        }.padding(.leading, 16).padding(.trailing, 8).padding(.vertical, 10)
            .background(Theme.surface)
    }
}

struct TranscriptDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.plainText] }
    var text: String
    init(text: String) { self.text = text }
    init(configuration: ReadConfiguration) throws {
        text = String(decoding: configuration.file.regularFileContents ?? Data(), as: UTF8.self)
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
}

struct ContextPanel: View {
    let dotID: String
    let room: String
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var exporting = false
    @State private var loading = false
    @State private var document = TranscriptDocument(text: "")
    @State private var error: String?
    private var usage: ContextUsage? { store.contextUsage[room] }
    private var messages: [ChatMessage] { store.messages[room] ?? [] }
    var body: some View {
        NavigationStack {
            Form {
                Section("Context") {
                    if let usage {
                        LabeledContent("Reported usage", value: usage.used.formatted() + " / " + usage.limit.formatted())
                    } else {
                        LabeledContent("Full context usage", value: "Not reported")
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("Full context usage: not reported")
                            .accessibilityIdentifier("full-context-status")
                    }
                    LabeledContent("Your planning target", value: ContextUsage.planningTarget.formatted() + " tokens")
                    LabeledContent("Send cutoff", value: store.contextBudget(room).sendLimit.formatted() + " tokens")
                    LabeledContent("Reserved buffer", value: store.contextBudget(room).reserve.formatted() + " tokens (10%)")
                    LabeledContent("Loaded text estimate", value: "~" + ContextUsage.visibleEstimate(messages).formatted() + " tokens")
                    Text("The estimate covers loaded message text only. Hidden instructions, memories, tool output, and earlier pages can change the actual context. Your planning target is not a verified model limit.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("The app stops new sends and retries at the cutoff, including an estimate for your draft. The reserve leaves room for a reply. Unknown provider context and reply size mean this cannot guarantee that the full context stays below the target.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    NavigationLink {
                        ConversationTextView(dotID: dotID, room: room)
                    } label: {
                        Label("View conversation text", systemImage: "text.alignleft")
                    }.accessibilityIdentifier("view-conversation-text")
                    Button {
                        loading = true; error = nil
                        Task {
                            defer { loading = false }
                            do {
                                document = TranscriptDocument(text: try await store.exportConversation(room: room, dotID: dotID))
                                exporting = true
                            } catch { self.error = error.localizedDescription }
                        }
                    } label: {
                        if loading { ProgressView("Loading full conversation…") }
                        else { Label("Save full conversation", systemImage: "square.and.arrow.down") }
                    }.disabled(loading)
                } footer: {
                    Text("Save a copy before starting a fresh conversation. Exporting does not reset or reduce your Dot’s context.")
                }
                Section("Reset and memory") {
                    Text("A context window is the information a model can use for an interaction. It is not a balance of tokens you spend down.")
                    Text("A verified context reset is not available in this app. Reconnecting or exporting does not reset context or erase your Dot’s saved memories, and does not grant a new usage allowance.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Link("How Dot context and memory work", destination: URL(string: "https://learn.chatgpt.com/docs/dots/tasks-and-memory")!)
                }
                Section("Connection and response time") {
                    LabeledContent("Route", value: store.account?.bluetoothID != nil ? "Bluetooth through Mac" : store.account?.relayURL == DotsStore.hostedRelay ? "HTTPS through Dots server" : store.account?.relayURL != nil ? "Network through Mac" : "Direct")
                    if let seconds = store.historyReadSeconds[room] {
                        LabeledContent("Last history fetch", value: seconds.formatted(.number.precision(.fractionLength(1))) + "s")
                    }
                    Text("The app checks for replies about once a second while waiting, and every two seconds otherwise, plus transfer time. Generation happens on the provider and may take longer. Replies appear when available; live token streaming is not yet supported.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Credits") {
                    ForEach(store.activeTasks[dotID] ?? []) { task in
                        Label(task.title + " · may use credits", systemImage: "creditcard")
                    }
                    if room.hasPrefix("mac-codex-") {
                        Text("Messages use the existing local Codex session and its Codex allowance. Sending while it is working steers the active turn; sending while idle starts a turn. Each send requires your approval.")
                    } else if room.hasPrefix("hub-") {
                        Text("Each responding hosted agent uses a Codex turn, including ordinary conversation. These turns use your Codex allowance and may consume credits. You approve the responding members before sending.")
                    } else {
                        Text("Conversation with your Dot does not count toward ChatGPT usage limits. Work or Codex tasks it delegates use their allowance and can consume credits.")
                    }
                    Text("Draft notices are intent estimates. The app cannot predict every tool choice or quote an exact credit cost before the service starts a task.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Link("OpenAI usage and pricing", destination: URL(string: "https://learn.chatgpt.com/docs/pricing")!)
                }
                Section("Work approvals and Pause") {
                    if room.hasPrefix("mac-codex-") {
                        Text("Stop interrupts the current turn. It does not pause child agents, external jobs or a persistent Goal. Native permission requests and questions remain in Codex on the Mac. This connection preserves the session’s current instructions and permissions.")
                    } else {
                    Text(room.hasPrefix("hub-") ? "You control Pause and Resume. Hosted agents share their saved session across rooms; pausing a member affects every room it belongs to. Resume does not start work." : "You control Pause and Resume in the chat toolbar or Dot details. The provider applies the state change; pausing its main task does not stop every delegated job or schedule.")
                    Text(room.hasPrefix("hub-") ? "Every hosted send requires approval for the responding Codex turns. Native permission requests appear for review in the chat. Approving one operation does not grant root access or future permission." : "Detected coding, separate job, and external-action requests require approval before this app sends them. Ordinary conversation and read-only lookups are allowed. This is a request confirmation, not a provider-wide execution gate; the service can act outside this app.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Link("Provider custom rules and approvals", destination: URL(string: "https://learn.chatgpt.com/docs/dots/controls")!)
                    }
                }
                if let error { Section { InlineError(text: error) } }
            }
            .navigationTitle("Context & credits").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .fileExporter(isPresented: $exporting, document: document, contentType: .plainText,
                          defaultFilename: "Dots-conversation") { result in
                if case .failure(let failure) = result { error = failure.localizedDescription }
            }
        }
    }
}

private struct ConversationTextView: View {
    let dotID: String
    let room: String
    @Environment(DotsStore.self) private var store
    @State private var text: String?
    @State private var error: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("This is the visible conversation, not the model’s hidden context or saved memories.")
                    .font(.footnote).foregroundStyle(.secondary)
                if let text { Text(text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                else if let error { InlineError(text: error) }
                else { ProgressView("Loading conversation…") }
            }.padding()
        }.navigationTitle("Conversation text").navigationBarTitleDisplayMode(.inline)
        .task {
            do { text = try await store.exportConversation(room: room, dotID: dotID) }
            catch { self.error = error.localizedDescription }
        }
    }
}

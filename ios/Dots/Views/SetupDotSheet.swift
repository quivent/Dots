import SwiftUI

private struct ChatPerson: Identifiable {
    let id: String
    let name: String
    let isSelf: Bool
}

struct HostedRoomSheet: View {
    var onReady: (Dot) -> Void
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var ownName = ""
    @State private var people: [ChatPerson] = []
    @State private var selectedPeople = Set<String>()
    @State private var selected = Set<String>()
    @State private var requestID = UUID().uuidString
    @State private var working = false
    @State private var loading = true
    @State private var failure: String?
    private var agents: [Dot] { store.dots.filter { $0.isHosted && $0.id.hasPrefix("hosted-") } }
    var body: some View {
        NavigationStack {
            Form {
                Section("Chat") { TextField("Chat name (optional)", text: $name).disabled(working) }
                Section("People") {
                    if loading { ProgressView("Loading people…") }
                    else {
                        TextField("Your display name", text: $ownName).disabled(working).accessibilityIdentifier("chat-display-name")
                        ForEach(people.filter { !$0.isSelf }) { person in
                            Toggle(person.name, isOn: Binding(get: { selectedPeople.contains(person.id) }, set: {
                                if $0 { selectedPeople.insert(person.id) } else { selectedPeople.remove(person.id) }
                            })).disabled(working).accessibilityIdentifier("person-" + person.id)
                        }
                        if people.allSatisfy({ $0.isSelf }) {
                            Text("No other people yet. Invite their phone from Account → Invite a phone.").font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("Dots (optional)") {
                    ForEach(agents) { agent in
                        Toggle(agent.name, isOn: Binding(get: { selected.contains(agent.id) }, set: {
                            if $0 { selected.insert(agent.id) } else { selected.remove(agent.id) }
                        })).disabled(working)
                    }
                }
                Section {
                    Text(selected.isEmpty ? "With just people, messages go directly to the chat. No agent turns or AI credits." : "Selected Dots listen and respond when relevant. Each listening check is an approved Codex turn and may use credits. Dots reuse their saved context across chats.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let failure { Section { InlineError(text: failure) } }
                Button {
                    working = true; failure = nil
                    Task {
                        defer { working = false }
                        do {
                            guard let account = store.account else { throw APIError.invalidSession }
                            _ = try await store.api.request("POST", "/hosted/people/me", account: account, body: ["name": ownName.trimmingCharacters(in: .whitespacesAndNewlines)])
                            let title = name.trimmingCharacters(in: .whitespacesAndNewlines)
                            let suggested = ([ownName] + people.filter { selectedPeople.contains($0.id) }.map(\.name) + agents.filter { selected.contains($0.id) }.map(\.name)).joined(separator: " & ")
                            let dot = try await store.createHostedRoom(name: title.isEmpty ? String(suggested.prefix(80)) : title, members: selected.sorted(), requestID: requestID, people: selectedPeople.sorted())
                            dismiss(); onReady(dot)
                        } catch { failure = error.localizedDescription }
                    }
                } label: {
                    if working { ProgressView("Creating chat…") } else { Text("Create chat") }
                }.disabled(working || loading || (selected.isEmpty && selectedPeople.isEmpty) || ownName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || ownName.count > 80 || name.count > 80)
                    .accessibilityIdentifier("create-people-chat")
            }.navigationTitle("New chat")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(working) } }
                .task {
                    defer { loading = false }
                    do {
                        guard let account = store.account else { throw APIError.invalidSession }
                        let result = try await store.api.request("GET", "/hosted/people", account: account)
                        people = (result["items"] as? [[String: Any]] ?? []).compactMap { p in
                            guard let id = p["id"] as? String, let name = p["name"] as? String else { return nil }
                            return ChatPerson(id: id, name: name, isSelf: p["is_self"] as? Bool ?? false)
                        }
                        ownName = people.first(where: { $0.isSelf })?.name ?? ""
                    } catch { failure = "Couldn’t load people. Close this screen and try again." }
                }
        }.interactiveDismissDisabled(working)
    }
}

struct HostedApproval: Identifiable {
    let id: String
    let agent: String
    let details: String
}

struct HostedApprovalSheet: View {
    let approval: HostedApproval
    var onDecision: (Bool) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var working = false
    @State private var failure: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(approval.agent + " requests permission").font(.headline)
                    Text("Review this exact operation. Approval applies once; it does not grant root access or permission for future operations.")
                    Text(approval.details).font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    if let failure { InlineError(text: failure) }
                    HStack {
                        Button("Deny", role: .destructive) { decide(false) }
                        Spacer()
                        Button("Approve once") { decide(true) }.buttonStyle(.borderedProminent)
                    }.disabled(working)
                }.padding()
            }.navigationTitle("Approve operation")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Later") { dismiss() }.disabled(working) } }
        }.interactiveDismissDisabled(working)
    }
    private func decide(_ accept: Bool) {
        working = true; failure = nil
        Task {
            defer { working = false }
            do { try await onDecision(accept); dismiss() }
            catch { failure = error.localizedDescription }
        }
    }
}

/// Each forward action performs setup; leaving the sheet preserves completed work.
struct SetupDotSheet: View {
    var existingID: String? = nil
    var onReady: (Dot) -> Void
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var selectedID: String?
    @State private var working = false
    @State private var error: String?
    @State private var review = false

    private var dot: Dot? {
        store.dots.first { $0.id == (selectedID ?? existingID) }
    }
    private var canCreate: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed.count <= 80 && !working && !store.uncertainCreation
    }
    private var unfinished: [Dot] { store.dots.filter { $0.roomID == nil } }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 12) {
                        if let dot { DotAvatar(dot: dot, size: 72) } else { DotMark(size: 72) }
                        Text(dot?.name ?? "A Dot of your own")
                            .font(.title2.weight(.semibold))
                        Text(dot == nil ? "Give it a name to get started." :
                                (dot?.roomID == nil ? "Your Dot is saved. Next, set up its conversation." : "Your Dot and chat are ready."))
                            .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }.frame(maxWidth: .infinity).padding(.vertical, 12)
                }.listRowBackground(Color.clear)

                Section {
                    setupRow("Create your Dot", number: 1, complete: dot != nil, active: dot == nil)
                    setupRow("Set up its chat", number: 2, complete: dot?.roomID != nil, active: dot != nil && dot?.roomID == nil)
                }

                if dot == nil {
                    Section {
                        TextField("Name your Dot", text: $name).accessibilityIdentifier("dot-name")
                            .submitLabel(.done).disabled(working)
                        if name.trimmingCharacters(in: .whitespacesAndNewlines).count > 80 {
                            Text("Use a name of 80 characters or fewer.").font(.caption).foregroundStyle(.red)
                        }
                    }
                    if !unfinished.isEmpty {
                        Section {
                            Menu {
                                ForEach(unfinished) { item in
                                    Button(item.name) { selectedID = item.id; error = nil }
                                        .accessibilityIdentifier("continue-" + item.id)
                                }
                            } label: {
                                Label("Choose an existing Dot", systemImage: "circle.grid.2x2")
                            }.disabled(working).accessibilityIdentifier("choose-existing-dot")
                        }
                    }
                }

                if store.uncertainCreation && dot == nil {
                    Section {
                        Text("The last creation couldn’t be confirmed. Check your Dots before creating another.")
                        Button("Refresh Dots") {
                            working = true; error = nil
                            Task {
                                await store.refresh()
                                error = store.error
                                store.error = nil
                                working = false
                            }
                        }.disabled(working)
                        // A recovered Dot can be opened here instead of creating it again.
                        ForEach(store.dots.filter { $0.roomID != nil }) { item in
                            Button("Open " + item.name) { selectedID = item.id; error = nil }
                                .disabled(working)
                        }
                        Button("The previous Dot is missing") { review = true }.disabled(working)
                    }
                }

                if let error { Section { InlineError(text: error) } }
            }
            .safeAreaInset(edge: .bottom) {
                forwardAction
                    .buttonStyle(ProminentButtonStyle())
                    .padding(16).background(.bar)
            }
            .navigationTitle(dot?.roomID != nil ? "Ready to chat" : "Set up a Dot")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(dot == nil ? "Cancel" : "Finish later") { dismiss() }.disabled(working)
                }
            }
            .interactiveDismissDisabled(working)
            .confirmationDialog("Only create again if the previous Dot is missing.", isPresented: $review) {
                Button("I’ve checked; it’s missing") { store.acknowledgeCreationReview() }
            }
        }
    }

    @ViewBuilder
    private var forwardAction: some View {
        if let dot {
            if dot.roomID != nil {
                Button("Open chat") { dismiss(); onReady(dot) }
                    .accessibilityIdentifier("setup-open-chat")
            } else {
                Button {
                    working = true; error = nil
                    Task {
                        defer { working = false }
                        do { _ = try await store.createChat(dot: dot) }
                        catch { self.error = error.localizedDescription }
                    }
                } label: {
                    if working { ProgressView("Setting up chat…") } else { Text("Set up chat") }
                }.disabled(working).accessibilityIdentifier("setup-create-chat")
            }
        } else {
            Button {
                working = true; error = nil
                Task {
                    defer { working = false }
                    do { selectedID = try await store.create(name: name).id }
                    catch { self.error = error.localizedDescription }
                }
            } label: {
                if working { ProgressView("Creating your Dot…") } else { Text("Create Dot") }
            }.disabled(!canCreate).accessibilityIdentifier("setup-create-dot")
        }
    }

    private func setupRow(_ title: String, number: Int, complete: Bool, active: Bool) -> some View {
        HStack(spacing: 12) {
            if complete {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).frame(width: 26)
            } else {
                Text(String(number)).font(.subheadline.weight(.semibold))
                    .foregroundStyle(active ? Theme.accent : Color.secondary)
                    .frame(width: 26, height: 26).background(Theme.surface, in: Circle())
            }
            Text(title).foregroundStyle(complete || active ? Color.primary : Color.secondary)
            Spacer()
            if complete { Text("Done").font(.caption).foregroundStyle(.secondary) }
        }.padding(.vertical, 4)
    }
}

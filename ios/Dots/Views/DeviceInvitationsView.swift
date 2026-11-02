import SwiftUI

private struct InvitedPhone: Identifiable {
    let id: String
    let name: String
    let revoked: Bool
    let studioRead: Bool
}

struct DeviceInvitationsView: View {
    @Environment(DotsStore.self) private var store
    @State private var includeWork = true
    @State private var code: String?
    @State private var expires: Date?
    @State private var phones: [InvitedPhone] = []
    @State private var working = false
    @State private var failure: String?
    @State private var revoking: InvitedPhone?
    @State private var nearby = NearbyInvitation()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Form {
            Section {
                Text("Invite a phone to your hosted Dots, shared chats and research Bank. The invited person can send approved Codex turns using this server’s allowance. Your Mac-backed ChatGPT account Dots are not included.")
                Toggle("Include shared Work tasks and crew",isOn:$includeWork)
                Text("Work access is read only. Private crew conversations, agent controls and private scene assets are not shared.").font(.footnote).foregroundStyle(.secondary)
                Button(code == nil ? "Create invitation" : "Create a new invitation") {
                    run {
                        try await createInvitation()
                    }
                }.disabled(working).accessibilityIdentifier("create-server-invitation")
                Button {
                    run {
                        try await createInvitation()
                        if let code, let expires { nearby.start(code: code, expires: expires) }
                    }
                } label: { Label("Invite nearby", systemImage: "antenna.radiowaves.left.and.right") }
                    .disabled(working || nearby.active).accessibilityIdentifier("invite-nearby")
                if !nearby.status.isEmpty { Text(nearby.status).font(.footnote).foregroundStyle(.secondary) }
                if nearby.active { Button("Stop nearby sharing") { nearby.stop() } }
            } footer: { Text("One use, valid for ten minutes. A new invitation replaces your previous unused code. No Mac access or ChatGPT sign-in is needed on the invited phone.") }
            if let code, let expires {
                Section("Invitation") {
                    Text(code).font(.largeTitle.monospaced().weight(.semibold)).textSelection(.enabled)
                        .frame(maxWidth: .infinity).accessibilityIdentifier("server-invitation-code")
                    Text("Expires " + expires.formatted(date: .omitted, time: .shortened)).font(.caption)
                    ShareLink(item: "Join my Dots server: \(DotsStore.hostedRelay)\nOn Android choose Enter invitation code; on iPhone choose Join an existing Dots server. Enter \(code).\nValid until \(expires.formatted()). This shares hosted Dots, shared chats and the research Bank.") {
                        Label("Share invitation", systemImage: "square.and.arrow.up")
                    }
                }
            }
            Section("Invited phones") {
                if phones.isEmpty { Text("No invited phones yet").foregroundStyle(.secondary) }
                ForEach(phones) { phone in
                    HStack {
                        VStack(alignment:.leading){
                            Text(phone.name)
                            if !phone.revoked{Button(phone.studioRead ? "Remove Work access":"Allow Work tasks and crew"){
                                run{
                                    guard let account=store.account else{throw APIError.invalidSession}
                                    let grant:Any=phone.studioRead ? NSNull():["project":"fmvisual","capabilities":["tasks.read","crew.read"]]
                                    _ = try await store.api.request("POST","/hosted/devices/"+DotsAPI.segment(phone.id)+"/studio-access",account:account,body:["studio_access":grant])
                                    try await reload()
                                }
                            }.font(.caption).disabled(working)}
                        }; Spacer()
                        if phone.revoked { Text("Revoked").foregroundStyle(.secondary) }
                        else { Button("Revoke", role: .destructive) { revoking = phone }.disabled(working) }
                    }
                }
            }
            if let failure { Section { InlineError(text: failure) } }
        }
        .navigationTitle("Invite a phone").navigationBarTitleDisplayMode(.inline)
        .task { do { try await reload() } catch { failure = error.localizedDescription } }
        .onDisappear { nearby.stop() }
        .onChange(of: scenePhase) { _, phase in if phase == .background { nearby.stop() } }
        .alert("Let this nearby phone join?", isPresented: Binding(get: { nearby.needsApproval }, set: { _ in })) {
            Button("Allow") { nearby.approve() }
            Button("Decline", role: .cancel) { nearby.decline() }
        } message: {
            Text("Only allow this while the person you are inviting is joining nearby. This shares your hosted Dots, chats and Bank, including permission to approve Codex turns using the server’s allowance.")
        }
        .confirmationDialog("Revoke this phone’s server access?", isPresented: Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } }), titleVisibility: .visible) {
            if let phone = revoking {
                Button("Revoke " + phone.name, role: .destructive) {
                    run {
                        guard let account = store.account else { throw APIError.invalidSession }
                        _ = try await store.api.request("POST", "/hosted/devices/" + DotsAPI.segment(phone.id) + "/revoke", account: account, body: [:])
                        revoking = nil; try await reload()
                    }
                }
            }
            Button("Cancel", role: .cancel) { revoking = nil }
        } message: { Text("This prevents new server requests. It does not cancel work the server has already accepted.") }
    }

    @MainActor private func run(_ block: @escaping () async throws -> Void) {
        working = true; failure = nil
        Task { defer { working = false }; do { try await block() } catch { failure = error.localizedDescription } }
    }
    @MainActor private func reload() async throws {
        guard let account = store.account else { throw APIError.invalidSession }
        let response = try await store.api.request("GET", "/hosted/devices", account: account)
        phones = (response["items"] as? [[String: Any]] ?? []).compactMap {
            guard let id = $0["id"] as? String, let name = $0["name"] as? String else { return nil }
            let grant=$0["studio_access"] as? [String:Any]
            let capabilities=Set(grant?["capabilities"] as? [String] ?? [])
            return InvitedPhone(id: id, name: name, revoked: ($0["revoked"] as? Int ?? 0) != 0,studioRead:grant?["project"] as? String=="fmvisual" && capabilities.isSuperset(of:["tasks.read","crew.read"]))
        }
    }

    @MainActor private func createInvitation() async throws {
        nearby.stop()
        guard let account = store.account else { throw APIError.invalidSession }
        let result = try await store.api.request("POST", "/hosted/invitations", account: account, body: includeWork ? ["studio_access":["project":"fmvisual","capabilities":["tasks.read","crew.read"]]]:[:])
        guard let value = result["code"] as? String, let seconds = result["expires_in"] as? Int else { throw APIError.invalidResponse }
        code = value; expires = Date().addingTimeInterval(Double(seconds))
    }
}

struct JoinServerView: View {
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var working = false
    @State private var failure: String?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Server", value: "dots.kosmos.institute")
                    TextField("Eight-digit invitation", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                        .onChange(of: code) { _, value in code = String(value.filter { "0123456789".contains($0) }.prefix(8)) }
                    Text("Ask the server owner for an invitation from Account → Invite a phone. You do not need their Mac or a ChatGPT login.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Button("Join server") {
                        working = true; failure = nil
                        Task {
                            defer { working = false }
                            do {
                                let session = try await NetworkPairing.pair(address: DotsStore.hostedRelay, code: code)
                                try await store.connect(session); dismiss()
                            } catch { failure = "Couldn’t join. Check your connection and ask for a new invitation if this one expired or was already used." }
                        }
                    }.disabled(working || code.count != 8)
                }
                if let failure { Section { InlineError(text: failure) } }
            }.navigationTitle("Join a Dots server")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(working) } }
        }.interactiveDismissDisabled(working)
    }
}

import SwiftUI

struct AccountView: View {
    @Environment(DotsStore.self) private var store
    @State private var signOut = false
    @State private var reconnect = false
    @State private var mac = false
    @State private var connectingServer = false
    @State private var connectionError: String?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label(store.isDemo ? "Preview" : "ChatGPT connected", systemImage: "person.crop.circle.fill")
                    if store.isDemo {
                        Text("Sample data. Nothing here changes your account.").font(.footnote).foregroundStyle(.secondary)
                    } else if store.account?.bluetoothID != nil {
                        LabeledContent("Connection", value: "Mac · Bluetooth")
                        if let name = store.account?.macName { Text(name).font(.footnote).foregroundStyle(.secondary) }
                    } else if let endpoint = store.account?.relayURL {
                        LabeledContent("Connection", value: endpoint == DotsStore.hostedRelay ? "Dots server · HTTPS" : "Through your Mac")
                        Text(endpoint).font(.footnote.monospaced()).foregroundStyle(.secondary)
                    } else {
                        LabeledContent("Connection", value: "Direct from this phone")
                    }
                }
                if !store.isDemo {
                    Section {
                        Text("dots.kosmos.institute").font(.subheadline.monospaced())
                        if store.account?.relayURL == DotsStore.hostedRelay {
                            Label("Connected", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                            if store.account?.hostedOnly != true {
                                NavigationLink("Invite a phone") { DeviceInvitationsView() }
                                    .accessibilityIdentifier("invite-server-phone")
                            }
                        } else if store.account?.bluetoothID != nil || store.account?.relayURL != nil {
                            Button {
                                connectingServer = true; connectionError = nil
                                Task {
                                    defer { connectingServer = false }
                                    do { try await store.connectHostedRelay() }
                                    catch { connectionError = error.localizedDescription }
                                }
                            } label: {
                                if connectingServer { ProgressView("Connecting…") }
                                else { Text("Connect to Dots server") }
                            }.disabled(connectingServer || store.loading || !store.sending.isEmpty)
                                .accessibilityIdentifier("connect-hosted-relay")
                        } else {
                            Text("Pair with your Mac first to get this phone’s connection credential.")
                        }
                        if let connectionError { InlineError(text: connectionError) }
                    } header: { Text("Dots server") } footer: {
                        Text("Works over cellular or Wi-Fi. Hosted agents run on the server. ChatGPT account Dots use the Mac connection and need the Mac awake.")
                    }
                }
                Section {
                    Button("Reconnect account session") { reconnect = true }
                    Button("Connect through your Mac") { mac = true }
                    Button(store.isDemo ? "Leave preview" : "Disconnect", role: .destructive) { signOut = true }
                } footer: {
                    Text("Account credentials and unsent message records are stored in this phone’s Keychain. Disconnecting removes them from this device.")
                }
                Section("About") {
                    LabeledContent("Dots", value: "0.1.0")
                    Text("Native iPhone companion for your Dots. Dot setup and chat setup are separate steps.").font(.footnote)
                    Link("Dots help", destination: URL(string: "https://learn.chatgpt.com/docs/dots/getting-started")!)
                }
            }
            .navigationTitle("Account")
            .sheet(isPresented: $reconnect) { SessionSheet(relay: false) }
            .sheet(isPresented: $mac) { MacConnectSheet() }
            .confirmationDialog("Disconnect this phone?", isPresented: $signOut, titleVisibility: .visible) {
                Button("Disconnect", role: .destructive) { store.disconnect() }
            } message: { Text("Your cloud Dots and chats stay in your ChatGPT account.") }
        }
    }
}

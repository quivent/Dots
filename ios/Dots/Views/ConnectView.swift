import SwiftUI
import WebKit

struct ConnectView: View {
    @Environment(DotsStore.self) private var store
    @State private var webLogin = false
    @State private var manual = false
    @State private var relay = false
    @State private var joinServer = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()
                DotMark(size: 80)
                VStack(spacing: 10) {
                    Text("Your Dots, with you.").font(Theme.display)
                    Text("Set up a Dot. Start a conversation.\nPick up where you left off.")
                        .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
                VStack(spacing: 18) {
                    Button("Connect through your Mac") { relay = true }.buttonStyle(ProminentButtonStyle())
                    Button("Join an existing Dots server") { joinServer = true }.font(.subheadline)
                    Button("Connect ChatGPT directly") { webLogin = true }.font(.subheadline)
                        .accessibilityIdentifier("Connect ChatGPT")
                    Button("Use an account session") { manual = true }.font(.footnote).foregroundStyle(.secondary)
                }.frame(maxWidth: 340).padding(.top, 8)
                Spacer()
                Text("Dots live in your ChatGPT account.")
                    .font(.caption).foregroundStyle(.tertiary)
                    .padding(.bottom, 24)
            }
            .padding(.horizontal, 28).background(Theme.background)
            .sheet(isPresented: $webLogin) { WebLoginView() }
            .sheet(isPresented: $manual) { SessionSheet(relay: false) }
            .sheet(isPresented: $relay) { MacConnectSheet() }
            .sheet(isPresented: $joinServer) { JoinServerView() }
        }
    }
}

@MainActor @Observable
final class WebLogin {
    let webView: WKWebView
    init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.load(URLRequest(url: URL(string: "https://chatgpt.com/auth/login")!))
    }
    func capture() async throws -> AccountSession {
        guard webView.url?.host == "chatgpt.com", webView.url?.scheme == "https" else { throw APIError.invalidSession }
        let object = try await webView.callAsyncJavaScript(
            "const r = await fetch('/api/auth/session', {credentials:'include'}); if (!r.ok) throw new Error('Not signed in'); return await r.json();",
            arguments: [:], in: nil, contentWorld: .page)
        guard let session = object as? [String: Any], let token = session["accessToken"] as? String,
              let accountID = AccountSession.accountID(from: token) else { throw APIError.invalidSession }
        return AccountSession(accessToken: token, accountID: accountID)
    }
}

struct LoginBrowser: UIViewRepresentable {
    let login: WebLogin
    func makeUIView(context: Context) -> WKWebView { login.webView }
    func updateUIView(_ view: WKWebView, context: Context) {}
}

struct WebLoginView: View {
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var login = WebLogin()
    @State private var connecting = false
    @State private var error: String?
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                LoginBrowser(login: login)
                VStack(spacing: 10) {
                    if let error { InlineError(text: error) }
                    Text("Sign in here, then connect this account. Your session stays on this phone.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button {
                        connecting = true; error = nil
                        Task {
                            defer { connecting = false }
                            do { try await store.connect(login.capture()); dismiss() }
                            catch { self.error = "Couldn’t connect this session. Finish signing in, then try again. If sign-in is blocked, use an account session or connect through your Mac." }
                        }
                    } label: {
                        if connecting { ProgressView().tint(.white) } else { Text("Use this account") }
                    }.buttonStyle(ProminentButtonStyle()).disabled(connecting)
                }.padding(16).background(.bar)
            }
            .navigationTitle("Connect ChatGPT").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .interactiveDismissDisabled(connecting)
        }
    }
}

struct SessionSheet: View {
    let relay: Bool
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var endpoint = ""
    @State private var token = ""
    @State private var accountID = ""
    @State private var error: String?
    @State private var connecting = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if relay {
                        TextField("http://your-mac:8769", text: $endpoint).keyboardType(.URL)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    SecureField(relay ? "Connection token" : "ChatGPT access token", text: $token)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    if !relay {
                        TextField("Account ID", text: $accountID).textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                } footer: {
                    Text(relay ? "Run dots mobile on your Mac. Connect using its address over your private network or Tailscale. Paste the separate connection token shown there."
                         : "Use a ChatGPT account session with Dot access. An OpenAI Platform API key does not grant access to your Dots. The session is verified before being saved in Keychain.")
                }
                if let error { Section { InlineError(text: error) } }
                Section {
                    Button {
                        connecting = true; error = nil
                        Task {
                            defer { connecting = false }
                            let value = token.trimmingCharacters(in: .whitespacesAndNewlines)
                            let id = relay ? "mac" : accountID.trimmingCharacters(in: .whitespacesAndNewlines)
                            let session = AccountSession(accessToken: value, accountID: id,
                                                         relayURL: relay ? endpoint.trimmingCharacters(in: .whitespacesAndNewlines) : nil)
                            do { try await store.connect(session); token = ""; dismiss() }
                            catch { self.error = error.localizedDescription }
                        }
                    } label: { if connecting { ProgressView() } else { Text("Connect") } }
                    .disabled(connecting || token.isEmpty || (relay ? AccountSession.validRelay(endpoint) == nil : accountID.isEmpty))
                }
            }
            .navigationTitle(relay ? "Connect your Mac" : "Account session").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .interactiveDismissDisabled(connecting)
        }
    }
}

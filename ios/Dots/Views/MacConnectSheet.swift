import SwiftUI

struct MacConnectSheet: View {
    @Environment(DotsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var bluetooth = BluetoothClient.shared
    @State private var discovery = MacDiscovery()
    @State private var useBluetooth = true
    @State private var selectedBluetooth: NearbyMac?
    @State private var selectedNetwork: NetworkMac?
    @State private var address = ""
    @State private var code = ""
    @State private var error: String?
    @State private var pairing = false
    @State private var advanced = false
    private enum Field: Hashable { case address, code }
    @FocusState private var focusedField: Field?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Use your Mac’s ChatGPT sign-in", systemImage: "desktopcomputer")
                    Text("Open Dots Mac from your Mac’s menu bar and choose Pair iPhone. Your login stays on the Mac.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Picker("Connection", selection: $useBluetooth) {
                        Text("Bluetooth").tag(true)
                        Text("Wi-Fi").tag(false)
                    }.pickerStyle(.segmented)
                }
                Section("Nearby Macs") {
                    if useBluetooth {
                        ForEach(bluetooth.nearby) { mac in
                            Button {
                                selectedBluetooth = mac; error = nil
                            } label: {
                                HStack { Label(mac.name, systemImage: "desktopcomputer"); Spacer()
                                    if selectedBluetooth?.id == mac.id { Image(systemName: "checkmark") }
                                }
                            }.disabled(pairing).accessibilityIdentifier("nearby-mac-\(mac.id)")
                        }
                        if bluetooth.nearby.isEmpty { Text(bluetooth.status).foregroundStyle(.secondary) }
                    } else {
                        ForEach(discovery.endpoints) { mac in
                            Button {
                                selectedNetwork = mac; address = mac.address; error = nil
                            } label: {
                                HStack { Label(mac.name, systemImage: "desktopcomputer"); Spacer()
                                    if selectedNetwork?.id == mac.id { Image(systemName: "checkmark") }
                                }
                            }.disabled(pairing)
                        }
                        if discovery.endpoints.isEmpty { Text(discovery.errorText ?? "Looking for your Mac on the local network…").foregroundStyle(.secondary) }
                    }
                    Button("Search again") { startDiscovery() }.disabled(pairing)
                }
                if !useBluetooth {
                    Section {
                        DisclosureGroup("Enter an address manually") {
                            TextField("http://your-mac.local:8769", text: $address)
                                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                                .focused($focusedField, equals: .address)
                                .disabled(pairing)
                        }
                    }
                }
                Section {
                    TextField("6-digit code from your Mac", text: $code)
                        .keyboardType(.numberPad).font(.title2.monospaced()).disabled(pairing)
                        .textContentType(.oneTimeCode)
                        .focused($focusedField, equals: .code)
                        .accessibilityIdentifier("pairing-code")
                        .onChange(of: code) { _, value in
                            code = String(value.filter { "0123456789".contains($0) }.prefix(6))
                            if code.count == 6 { focusedField = nil }
                        }
                } header: { Text("Pairing code") } footer: {
                    Text("Codes work once and expire after two minutes. After pairing, Dots reconnects automatically while your Mac is awake and reachable.")
                }
                if useBluetooth, selectedBluetooth == nil {
                    Section { Text("Choose a nearby Mac above to enable pairing.").foregroundStyle(.secondary) }
                }
                if let error { Section { InlineError(text: error) } }
                Section {
                    Button("Use an existing connection token") { advanced = true }.font(.footnote)
                }
            }
            .navigationTitle("Connect your Mac").navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                Button {
                    focusedField = nil
                    pairing = true; error = nil
                    Task {
                        defer { pairing = false }
                        do {
                            let session: AccountSession
                            if useBluetooth, let mac = selectedBluetooth {
                                session = try await bluetooth.pair(mac: mac.id, code: code)
                            } else {
                                session = try await NetworkPairing.pair(address: address, code: code)
                            }
                            try await store.connectPairedMac(session)
                            dismiss()
                        } catch { self.error = error.localizedDescription }
                    }
                } label: {
                    if pairing { ProgressView("Pairing…").tint(.white) } else { Text("Pair this Mac") }
                }
                .buttonStyle(ProminentButtonStyle())
                .accessibilityIdentifier("pair-mac")
                .disabled(pairing || code.count != 6 || (useBluetooth ? selectedBluetooth == nil : AccountSession.validRelay(address) == nil))
                .padding(16).background(.bar)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(pairing) }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { focusedField = nil }
                }
            }
            .interactiveDismissDisabled(pairing)
            .task { startDiscovery() }
            .onChange(of: useBluetooth) { _, _ in code = ""; error = nil; startDiscovery() }
            .onChange(of: bluetooth.nearby.map(\.id)) { _, ids in
                if selectedBluetooth == nil, ids.count == 1 { selectedBluetooth = bluetooth.nearby.first }
            }
            .onDisappear { bluetooth.stopScan(); discovery.stop() }
            .sheet(isPresented: $advanced) { SessionSheet(relay: true) }
        }
    }
    private func startDiscovery() {
        if useBluetooth {
            discovery.stop(); bluetooth.start()
            if selectedBluetooth == nil, bluetooth.nearby.count == 1 { selectedBluetooth = bluetooth.nearby.first }
        }
        else { bluetooth.stopScan(); discovery.start() }
    }
}

final class NetworkPairing: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }

    static func pair(address: String, code: String) async throws -> AccountSession {
        guard let url = AccountSession.validRelay(address) else { throw APIError.invalidSession }
        let delegate = NetworkPairing()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.urlCache = nil; configuration.httpCookieStorage = nil
        let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        var request = URLRequest(url: url.appendingPathComponent("v1/pair"))
        request.httpMethod = "POST"; request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["code": code])
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = object["token"] as? String else { throw MacPairingError.invalidCode }
        return AccountSession(accessToken: token, accountID: "mac", relayURL: url.absoluteString,
                              macName: object["name"] as? String, hostedOnly: object["scope"] as? String == "hosted")
    }
}

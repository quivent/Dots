import AppKit
import CoreBluetooth
import Foundation

final class DotsMac: NSObject, NSApplicationDelegate, CBPeripheralManagerDelegate {
    private var statusItem: NSStatusItem!
    private var status = NSMenuItem(title: "Starting Dots…", action: nil, keyEquivalent: "")
    private var bluetoothStatus = NSMenuItem(title: "Bluetooth starting…", action: nil, keyEquivalent: "")
    private var manager: CBPeripheralManager!
    private var output: CBMutableCharacteristic!
    private var receivers: [UUID: BluetoothFrames] = [:]
    private var subscribers: [UUID: CBCentral] = [:]
    private var outbound: [UUID: Data] = [:]
    private var inFlight: [UUID: Int] = [:]
    private var service: NetService?
    private var token = ""
    private let port = 8769
    private var daemonReady = false
    private var pairingWindow: NSWindow?
    private var pairingLabel: NSTextField?
    private var pairingPending = false
    private var receivedFrames = 0
    private var lastResponseStatus = 0
    private var desktop: DesktopWindow?

    private func writeStatus() {
        let file = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/dots/mac-status.json")
        let state: [String: Any] = ["daemon_running": daemonReady, "bluetooth": bluetoothStatus.title,
                                    "advertising": manager?.isAdvertising ?? false, "connected_phones": subscribers.count,
                                    "received_frames": receivedFrames, "last_response_status": lastResponseStatus]
        if let data = try? JSONSerialization.data(withJSONObject: state) { try? data.write(to: file, options: .atomic) }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let file = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/dots/mobile-token")
        token = (try? String(contentsOf: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) ?? ""
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "circle.hexagongrid.fill", accessibilityDescription: "Dots Mac")
        let menu = NSMenu()
        let open = NSMenuItem(title: "Open Dots", action: #selector(openDesktop), keyEquivalent: "")
        open.target = self; menu.addItem(open); menu.addItem(.separator())
        menu.addItem(status); menu.addItem(bluetoothStatus); menu.addItem(.separator())
        let pair = NSMenuItem(title: "Pair iPhone…", action: #selector(showPairing), keyEquivalent: "")
        pair.target = self; menu.addItem(pair)
        let revoke = NSMenuItem(title: "Disconnect all phones…", action: #selector(revokePhones), keyEquivalent: "")
        revoke.target = self; menu.addItem(revoke)
        let logs = NSMenuItem(title: "Open daemon logs", action: #selector(openLogs), keyEquivalent: "")
        logs.target = self; menu.addItem(logs)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Dots Mac", action: #selector(quit), keyEquivalent: "q")
        quit.target = self; menu.addItem(quit)
        statusItem.menu = menu
        manager = CBPeripheralManager(delegate: self, queue: .main)
        service = NetService(domain: "local.", type: "_dots._tcp.", name: Host.current().localizedName ?? "Dots Mac", port: Int32(port))
        service?.publish()
        updateStatus()
        let health = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.updateStatus() }
        health.tolerance = 10
        if let icon = Bundle.main.url(forResource: "AppIcon", withExtension: "png") {
            NSApp.applicationIconImage = NSImage(contentsOf: icon)
        }
        installApplicationMenu()
        if !CommandLine.arguments.contains("--background") { openDesktop() }
        if CommandLine.arguments.contains("--pair") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.showPairing() }
        }
    }

    @objc private func openDesktop() {
        if desktop == nil { desktop = DesktopWindow() }
        desktop?.open()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openDesktop(); return true
    }

    private func installApplicationMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); appItem.title = "Dots"; let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Dots", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Dots", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Dots", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; menu.addItem(appItem)
        let editItem = NSMenuItem(); editItem.title = "Edit"; let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit; menu.addItem(editItem)
        let windowItem = NSMenuItem(); windowItem.title = "Window"; let windows = NSMenu(title: "Window")
        let open = NSMenuItem(title: "Open Dots", action: #selector(openDesktop), keyEquivalent: "0")
        open.target = self; windows.addItem(open)
        windows.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowItem.submenu = windows; menu.addItem(windowItem)
        NSApp.mainMenu = menu; NSApp.windowsMenu = windows
    }

    private func admin(_ path: String, method: String = "GET", completion: @escaping (Int, [String: Any]) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/v1" + path)!)
        request.httpMethod = method; request.timeoutInterval = 10
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            DispatchQueue.main.async { completion((response as? HTTPURLResponse)?.statusCode ?? 503, object) }
        }.resume()
    }

    private func updateStatus() {
        admin("/health") { [weak self] code, _ in
            self?.daemonReady = code == 200
            self?.status.title = code == 200 ? "Dots daemon running · port 8769" : "Daemon unavailable · run dots mobile"
            self?.writeStatus()
        }
    }

    @objc private func showPairing() {
        if let pairingWindow { pairingWindow.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 250),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Connect your iPhone"; window.isReleasedWhenClosed = false
        let label = NSTextField(wrappingLabelWithString: "Getting a pairing code…")
        label.frame = NSRect(x: 24, y: 68, width: 392, height: 155)
        label.font = .systemFont(ofSize: 17)
        let refresh = NSButton(title: "New code", target: self, action: #selector(refreshPairing))
        refresh.frame = NSRect(x: 24, y: 20, width: 120, height: 32)
        window.contentView?.addSubview(label); window.contentView?.addSubview(refresh)
        pairingWindow = window; pairingLabel = label
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        refreshPairing()
    }

    @objc private func refreshPairing() {
        guard !pairingPending else { return }
        pairingPending = true
        admin("/pairing/start", method: "POST") { code, response in
            self.pairingPending = false
            if code == 200, let pairingCode = response["code"] as? String {
                self.pairingLabel?.stringValue = "In Dots on your iPhone, choose Connect through your Mac. Enter:\n\n\(pairingCode)\n\nValid for two minutes. Keep this window open while pairing."
            } else {
                self.pairingLabel?.stringValue = "The Dots background service is unavailable. Start the service, then choose New code."
            }
        }
    }

    @objc private func revokePhones() {
        let alert = NSAlert()
        alert.messageText = "Disconnect all paired phones?"
        alert.informativeText = "You can reconnect each phone with a new pairing code. Your ChatGPT sign-in stays on this Mac."
        alert.addButton(withTitle: "Disconnect phones"); alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn { admin("/pairing/revoke", method: "POST") { _, _ in } }
    }
    @objc private func openLogs() {
        NSWorkspace.shared.open(FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Dots"))
    }
    @objc private func quit() { NSApp.terminate(nil) }

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        if peripheral.state == .poweredOn {
            let input = CBMutableCharacteristic(type: CBUUID(string: BluetoothWire.input), properties: [.write], value: nil,
                                                permissions: [.writeEncryptionRequired])
            output = CBMutableCharacteristic(type: CBUUID(string: BluetoothWire.output),
                properties: [.notify, .notifyEncryptionRequired], value: nil, permissions: [.readEncryptionRequired])
            let service = CBMutableService(type: CBUUID(string: BluetoothWire.service), primary: true)
            service.characteristics = [input, output]
            peripheral.removeAllServices(); peripheral.add(service)
            bluetoothStatus.title = "Bluetooth ready"
        } else {
            bluetoothStatus.title = peripheral.state == .unauthorized ? "Bluetooth permission needed in System Settings" : "Bluetooth off or unavailable"
            receivers = [:]; subscribers = [:]; outbound = [:]; inFlight = [:]
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard error == nil else { bluetoothStatus.title = "Bluetooth service could not start"; return }
        peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: BluetoothWire.service)],
                                    CBAdvertisementDataLocalNameKey: Host.current().localizedName ?? "Dots Mac"])
    }
    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if error != nil { bluetoothStatus.title = "Bluetooth advertising failed" }
        writeStatus()
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didSubscribeTo characteristic: CBCharacteristic) {
        guard subscribers.count < 16 else { return }
        subscribers[central.identifier] = central
        bluetoothStatus.title = "Bluetooth · \(subscribers.count) phone(s) nearby"
        writeStatus()
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        subscribers[central.identifier] = nil; receivers[central.identifier] = nil
        outbound[central.identifier] = nil; inFlight[central.identifier] = nil
        bluetoothStatus.title = subscribers.isEmpty ? "Bluetooth ready" : "Bluetooth connected"
        writeStatus()
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        guard let first = requests.first else { return }
        var frames: [(CBCentral, [String: Any])] = []
        do {
            for request in requests {
                guard request.characteristic.uuid == CBUUID(string: BluetoothWire.input), request.offset == 0,
                      let bytes = request.value, subscribers[request.central.identifier] != nil else {
                    peripheral.respond(to: first, withResult: .requestNotSupported); return
                }
                var receiver = receivers[request.central.identifier] ?? BluetoothFrames(limit: BluetoothWire.maximumRequest)
                frames += try receiver.append(bytes).map { (request.central, $0) }
                receivers[request.central.identifier] = receiver
            }
            peripheral.respond(to: first, withResult: .success)
            for (central, frame) in frames { process(frame, central: central) }
        } catch {
            receivers[first.central.identifier] = nil
            peripheral.respond(to: first, withResult: .invalidAttributeValueLength)
        }
    }

    private func process(_ frame: [String: Any], central: CBCentral) {
        guard let id = frame["id"] as? String, UUID(uuidString: id) != nil else { return }
        receivedFrames += 1; writeStatus()
        guard inFlight[central.identifier, default: 0] < 4 else {
            respond(id: id, status: 429, body: ["error": "Too many pending Bluetooth requests."], central: central); return
        }
        let path: String
        let method: String
        var body = frame["body"] as? [String: Any]
        var bearer = frame["token"] as? String
        if frame["kind"] as? String == "pair" {
            path = "/pair"; method = "POST"; body = ["code": frame["code"] as? String ?? ""]; bearer = nil
        } else {
            guard let candidate = frame["path"] as? String,
                  candidate == "/tbo" || candidate.hasPrefix("/tbo/") || candidate.hasPrefix("/messaging/rooms/"),
                  let verb = frame["method"] as? String, ["GET", "POST"].contains(verb),
                  let token = bearer, !token.isEmpty, token.utf8.allSatisfy({ (33...126).contains($0) }) else {
                respond(id: id, status: 400, body: ["error": "Unsupported Bluetooth request."], central: central); return
            }
            path = candidate; method = verb
        }
        guard var components = URLComponents(string: "http://127.0.0.1:\(port)/v1" + path) else {
            respond(id: id, status: 400, body: ["error": "Invalid request path."], central: central); return
        }
        if let query = frame["query"] as? [String: String], !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let url = components.url else {
            respond(id: id, status: 400, body: ["error": "Invalid request URL."], central: central); return
        }
        var request = URLRequest(url: url)
        request.httpMethod = method; request.timeoutInterval = 90
        if let bearer { request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        inFlight[central.identifier, default: 0] += 1
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.inFlight[central.identifier] = max(0, self.inFlight[central.identifier, default: 1] - 1)
                guard self.subscribers[central.identifier] != nil else { return }
                guard let data, data.count < BluetoothWire.maximumResponse,
                      let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    self.respond(id: id, status: 502, body: ["error": "The daemon response could not be received."], central: central); return
                }
                self.respond(id: id, status: (response as? HTTPURLResponse)?.statusCode ?? 502, body: result, central: central)
            }
        }.resume()
    }

    private func respond(id: String, status: Int, body: [String: Any], central: CBCentral) {
        lastResponseStatus = status; writeStatus()
        if status == 200, body["token"] is String {
            pairingLabel?.stringValue = "Your iPhone is paired. You can close this window. Your ChatGPT login stays on this Mac."
        }
        guard let frame = try? BluetoothWire.encode(["id": id, "status": status, "body": body]),
              frame.count + outbound[central.identifier, default: Data()].count <= BluetoothWire.maximumResponse else { return }
        outbound[central.identifier, default: Data()].append(frame)
        flush()
    }
    private func flush() {
        for id in Array(outbound.keys) {
            guard let central = subscribers[id] else { outbound[id] = nil; continue }
            while let data = outbound[id], !data.isEmpty {
                let chunk = Data(data.prefix(central.maximumUpdateValueLength))
                guard manager.updateValue(chunk, for: output, onSubscribedCentrals: [central]) else { return }
                outbound[id]?.removeFirst(chunk.count)
            }
            outbound[id] = nil
        }
    }
    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) { flush() }
}

let application = NSApplication.shared
let delegate = DotsMac()
application.delegate = delegate
application.run()

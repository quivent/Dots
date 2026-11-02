import AppKit

final class DesktopWindow: NSWindowController, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate, NSTextViewDelegate {
    private let api = DesktopAPI()
    private let table = NSTableView()
    private let transcript = NSTextView()
    private let composer = NSTextView()
    private let heading = NSTextField(labelWithString: "Your Dots")
    private let detail = NSTextField(labelWithString: "Choose a Dot to start chatting.")
    private let status = NSTextField(wrappingLabelWithString: "Connecting…")
    private let send = NSButton(title: "Send", target: nil, action: nil)
    private let refresh = NSButton(title: "Refresh", target: nil, action: nil)
    private let pause = NSButton(title: "Pause", target: nil, action: nil)
    private let create = NSButton(title: "New Dot", target: nil, action: nil)
    private var dots: [DesktopDot] = []
    private var selected: DesktopDot? { dots.indices.contains(table.selectedRow) ? dots[table.selectedRow] : nil }
    private var historyBusy = false
    private var catalogBusy = false
    private var writing = false
    private var history: [String: DesktopMessage] = [:]
    private var olderCursor: String?
    private let older = NSButton(title: "Load earlier messages", target: nil, action: nil)
    private var poll: Timer?
    private var pollUntil: Date?
    private var replyBaseline: [String: String] = [:]
    private var replyReceived = false
    private var pending: [String: String]?
    private var unconfirmedCreation: String? { UserDefaults.standard.string(forKey: "DesktopPendingCreation") }
    private let pendingFile = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/dots/desktop-pending.json")

    init() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Dots"
        window.minSize = NSSize(width: 720, height: 520)
        window.setFrameAutosaveName("DotsDesktop")
        super.init(window: window)
        window.delegate = self
        if let data = try? Data(contentsOf: pendingFile) {
            pending = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        }
        build()
        window.center()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func button(_ button: NSButton, _ action: Selector) {
        button.target = self; button.action = action; button.bezelStyle = .rounded
    }

    private func scroll(_ text: NSTextView, editable: Bool) -> NSScrollView {
        let view = NSScrollView()
        view.hasVerticalScroller = true; view.borderType = .noBorder
        text.isEditable = editable; text.isSelectable = true
        text.isRichText = false; text.allowsUndo = editable
        text.font = .systemFont(ofSize: 14)
        text.textContainerInset = NSSize(width: 16, height: 14)
        text.isVerticallyResizable = true; text.isHorizontallyResizable = false
        text.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true
        view.documentView = text
        return view
    }

    private func build() {
        guard let content = window?.contentView else { return }
        button(send, #selector(sendMessage)); button(refresh, #selector(refreshAll))
        button(pause, #selector(togglePause)); button(create, #selector(newDot)); button(older, #selector(loadEarlier))
        send.keyEquivalent = "\r"; send.keyEquivalentModifierMask = [.command]
        send.bezelColor = .controlAccentColor
        composer.delegate = self
        composer.setAccessibilityLabel("Message")
        transcript.setAccessibilityLabel("Conversation")
        table.setAccessibilityLabel("Your Dots")
        heading.font = .systemFont(ofSize: 23, weight: .semibold)
        detail.textColor = .secondaryLabelColor
        status.font = .systemFont(ofSize: 12); status.textColor = .secondaryLabelColor
        status.maximumNumberOfLines = 3
        table.addTableColumn(NSTableColumn(identifier: NSUserInterfaceItemIdentifier("dots")))
        table.headerView = nil; table.rowHeight = 48
        table.style = .sourceList; table.delegate = self; table.dataSource = self
        let list = NSScrollView(); list.hasVerticalScroller = true; list.documentView = table
        let label = NSTextField(labelWithString: "DOTS"); label.font = .systemFont(ofSize: 11, weight: .semibold)
        label.textColor = .secondaryLabelColor
        let sidebar = NSStackView(views: [label, list, create])
        sidebar.orientation = .vertical; sidebar.alignment = .leading; sidebar.spacing = 12
        sidebar.edgeInsets = NSEdgeInsets(top: 24, left: 14, bottom: 18, right: 14)
        let sidebarBackground = NSVisualEffectView()
        sidebarBackground.material = .sidebar; sidebarBackground.blendingMode = .behindWindow
        sidebarBackground.addSubview(sidebar)
        sidebar.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([sidebar.leadingAnchor.constraint(equalTo: sidebarBackground.leadingAnchor),
            sidebar.trailingAnchor.constraint(equalTo: sidebarBackground.trailingAnchor),
            sidebar.topAnchor.constraint(equalTo: sidebarBackground.topAnchor),
            sidebar.bottomAnchor.constraint(equalTo: sidebarBackground.bottomAnchor),
            list.widthAnchor.constraint(equalTo: sidebar.widthAnchor, constant: -28),
            create.widthAnchor.constraint(equalTo: list.widthAnchor)])
        let titles = NSStackView(views: [heading, detail]); titles.orientation = .vertical; titles.alignment = .leading; titles.spacing = 5
        let spacer = NSView()
        let toolbar = NSStackView(views: [titles, spacer, pause, refresh]); toolbar.spacing = 10
        let chat = scroll(transcript, editable: false)
        transcript.backgroundColor = .textBackgroundColor
        let input = scroll(composer, editable: true)
        input.wantsLayer = true; input.layer?.cornerRadius = 9
        input.layer?.borderWidth = 1; input.layer?.borderColor = NSColor.separatorColor.cgColor
        input.heightAnchor.constraint(equalToConstant: 94).isActive = true
        let sendRow = NSStackView(views: [status, send]); sendRow.alignment = .centerY; sendRow.spacing = 12
        status.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let main = NSStackView(views: [toolbar, older, chat, input, sendRow])
        main.orientation = .vertical; main.alignment = .leading; main.spacing = 14
        main.edgeInsets = NSEdgeInsets(top: 24, left: 24, bottom: 18, right: 24)
        for view in [toolbar, chat, input, sendRow] {
            view.widthAnchor.constraint(equalTo: main.widthAnchor, constant: -48).isActive = true
        }
        chat.heightAnchor.constraint(greaterThanOrEqualToConstant: 180).isActive = true
        let split = NSSplitView(); split.isVertical = true; split.dividerStyle = .thin
        split.addArrangedSubview(sidebarBackground); split.addArrangedSubview(main)
        content.addSubview(split); split.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([split.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            split.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            split.topAnchor.constraint(equalTo: content.topAnchor), split.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            sidebarBackground.widthAnchor.constraint(equalToConstant: 220)])
        updateControls()
    }

    func open() {
        NSApp.setActivationPolicy(.regular)
        showWindow(nil); window?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        if dots.isEmpty { refreshAll() }
    }

    private func notice(_ text: String, error: Bool = false) {
        status.stringValue = text; status.toolTip = text
        status.textColor = error ? .systemRed : .secondaryLabelColor
    }

    private func updateControls() {
        send.isEnabled = selected?.room != nil && selected?.paused == false && !writing && pending == nil
            && !composer.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        pause.isEnabled = selected != nil && !writing
        pause.title = selected?.paused == true ? "Resume" : "Pause"
        create.isEnabled = !writing && !catalogBusy
        create.title = unconfirmedCreation == nil ? "New Dot" : "Check creation"
        refresh.isEnabled = !historyBusy && !catalogBusy
        older.isHidden = olderCursor == nil
        older.isEnabled = !historyBusy
    }

    func numberOfRows(in tableView: NSTableView) -> Int { dots.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let cell = NSTableCellView()
        let label = NSTextField(labelWithString: dots[row].name)
        label.font = .systemFont(ofSize: 14, weight: .medium)
        cell.addSubview(label); label.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([label.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 10),
            label.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -8), label.centerYAnchor.constraint(equalTo: cell.centerYAnchor)])
        cell.textField = label
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        stopPolling(); pollUntil = nil; history = [:]; olderCursor = nil
        transcript.string = ""
        guard let dot = selected else { updateControls(); return }
        UserDefaults.standard.set(dot.id, forKey: "DesktopSelectedDot")
        heading.stringValue = dot.name
        detail.stringValue = dot.paused ? "Paused · history is available" : "ChatGPT Dot"
        updateControls(); loadHistory()
    }

    @objc private func refreshAll() {
        guard !catalogBusy else { return }
        catalogBusy = true; notice("Loading your Dots…"); updateControls()
        let previous = selected?.id ?? UserDefaults.standard.string(forKey: "DesktopSelectedDot")
        api.catalog { [weak self] result in
            guard let self else { return }
            self.catalogBusy = false
            switch result {
            case .failure(let error): self.notice(error.message, error: true)
            case .success(let dots):
                if let pendingName = self.unconfirmedCreation,
                   dots.contains(where: { $0.name.caseInsensitiveCompare(pendingName) == .orderedSame }) {
                    UserDefaults.standard.removeObject(forKey: "DesktopPendingCreation")
                }
                self.dots = dots; self.table.reloadData()
                if let index = dots.firstIndex(where: { $0.id == previous }) ?? (dots.isEmpty ? nil : 0) {
                    self.table.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false)
                    self.tableViewSelectionDidChange(Notification(name: NSTableView.selectionDidChangeNotification))
                } else {
                    self.heading.stringValue = "Welcome to Dots"
                    self.notice("No Dots on this account. Choose New Dot to create one.")
                }
            }
            self.updateControls()
        }
    }

    @objc private func loadEarlier() { loadHistory(before: olderCursor) }

    private func loadHistory(before: String? = nil) {
        guard !historyBusy, let dot = selected else { return }
        guard let room = dot.room, !room.isEmpty else { notice("This Dot has no chat room. Run dots room NAME to recover it.", error: true); return }
        historyBusy = true; updateControls()
        var query = ["limit": "25"]
        if let before { query["before"] = before }
        api.request("GET", "/messaging/rooms/" + DesktopAPI.identifier(room) + "/messages", query: query) { [weak self] result in
            guard let self else { return }
            self.historyBusy = false
            guard self.selected?.id == dot.id else { self.updateControls(); self.loadHistory(); return }
            switch result {
            case .failure(let error): self.stopPolling(); self.notice(error.message, error: true)
            case .success(let json):
                guard let items = json["items"] as? [[String: Any]] else {
                    self.notice("Unexpected conversation response.", error: true); self.updateControls(); return
                }
                for item in items {
                    if let message = DesktopMessage(item) { self.history[message.id] = message }
                }
                if before != nil || self.history.count <= 25 { self.olderCursor = json["prev_cursor"] as? String }
                let messages = self.history.values.sorted { ($0.created, $0.id) < ($1.created, $1.id) }
                if let pending = self.pending, pending["room"] == room,
                   items.contains(where: { ($0["request_id"] as? String ?? $0["idempotency_token"] as? String) == pending["request_id"] }) {
                    self.clearPending()
                }
                self.render(messages, name: dot.name, keepPosition: before != nil)
                if let last = messages.last, !last.mine, self.pollUntil != nil,
                   self.replyBaseline[last.id] != last.text { self.replyReceived = true }
                if self.pending != nil { self.notice("Delivery is unconfirmed. Refresh checks it without resending.", error: true) }
                else if let name = self.unconfirmedCreation { self.notice("Creation of " + name + " is unconfirmed. Check the account before retrying.", error: true) }
                else if self.pollUntil != nil { self.notice(self.replyReceived ? "Reply received · checking for updates…" : "Message sent. Waiting for a reply…") }
                else { self.notice(dot.paused ? "Paused. Resume explicitly to send messages." : "Refresh checks for new messages · ⌘Return to send") }
            }
            self.updateControls()
        }
    }

    private func render(_ messages: [DesktopMessage], name: String, keepPosition: Bool) {
        let oldPosition = transcript.enclosingScrollView?.contentView.bounds.origin ?? .zero
        let wasAtBottom = transcript.visibleRect.maxY >= transcript.bounds.maxY - 36
        let text = NSMutableAttributedString(string: "")
        for message in messages {
            text.append(NSAttributedString(string: (message.mine ? "You" : name) + "\n", attributes: [
                .font: NSFont.systemFont(ofSize: 13, weight: .semibold), .foregroundColor: NSColor.controlAccentColor]))
            let paragraph = NSMutableParagraphStyle(); paragraph.lineSpacing = 4; paragraph.paragraphSpacing = 12
            text.append(NSAttributedString(string: message.text + "\n\n", attributes: [
                .font: NSFont.systemFont(ofSize: 14), .foregroundColor: NSColor.labelColor, .paragraphStyle: paragraph]))
        }
        if messages.isEmpty { text.append(NSAttributedString(string: "Start a conversation with " + name + ".", attributes: [.foregroundColor: NSColor.secondaryLabelColor])) }
        // Preserve selection and scrolling when a poll returns unchanged history.
        if transcript.string == text.string { return }
        transcript.textStorage?.setAttributedString(text)
        if keepPosition || !wasAtBottom { transcript.enclosingScrollView?.contentView.scroll(to: oldPosition) }
        else { transcript.scrollToEndOfDocument(nil) }
    }

    func textDidChange(_ notification: Notification) { updateControls() }

    @objc private func sendMessage() {
        guard send.isEnabled, let dot = selected, let room = dot.room else { return }
        let text = composer.string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.count <= 12000 else { notice("Messages can contain up to 12,000 characters.", error: true); return }
        let requestID = UUID().uuidString.lowercased()
        replyBaseline = history.filter { !$0.value.mine }.mapValues { $0.text }
        replyReceived = false
        pending = ["request_id": requestID, "room": room, "dot": dot.id]
        do {
            try FileManager.default.createDirectory(at: pendingFile.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: pending!)
            try data.write(to: pendingFile, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: pendingFile.path)
        } catch { pending = nil; notice("Could not save delivery tracking. Nothing was sent.", error: true); return }
        writing = true; notice("Sending…"); updateControls()
        let body: [String: Any] = ["content": ["text": text, "attachments": []], "request_id": requestID,
            "idempotency_token": requestID, "timezone_offset_min": -TimeZone.current.secondsFromGMT() / 60]
        api.request("POST", "/messaging/rooms/" + DesktopAPI.identifier(room) + "/messages", body: body) { [weak self] result in
            guard let self else { return }
            self.writing = false
            switch result {
            case .failure(let error):
                if let code = error.status, (400..<500).contains(code), code != 408 { self.clearPending() }
                self.notice(error.message, error: true)
            case .success(let response):
                guard let id = response["id"] as? String, !id.isEmpty else {
                    self.notice("Delivery is unconfirmed. Refresh checks it without resending.", error: true)
                    self.updateControls(); return
                }
                self.clearPending()
                if self.selected?.id == dot.id, self.composer.string.trimmingCharacters(in: .whitespacesAndNewlines) == text { self.composer.string = "" }
                if self.selected?.id == dot.id {
                    self.pollUntil = Date().addingTimeInterval(120); self.startPolling(); self.loadHistory()
                }
            }
            self.updateControls()
        }
    }

    private func clearPending() {
        do { if FileManager.default.fileExists(atPath: pendingFile.path) { try FileManager.default.removeItem(at: pendingFile) }; pending = nil }
        catch { notice("Delivery was checked, but tracking could not be cleared. Refresh to check again.", error: true) }
    }

    @objc private func togglePause() {
        guard let dot = selected, !writing else { return }
        writing = true; updateControls()
        api.request("POST", "/tbo/" + DesktopAPI.identifier(dot.id) + "/runtime/" + (dot.paused ? "resume" : "pause"), body: [:]) { [weak self] result in
            guard let self else { return }; self.writing = false
            switch result {
            case .failure(let error): self.notice(error.message, error: true)
            case .success: self.refreshAll()
            }
            self.updateControls()
        }
    }

    @objc private func newDot() {
        guard !writing else { return }
        if let name = unconfirmedCreation {
            notice("Creation of " + name + " is unconfirmed. Refresh checks the account without creating another Dot.", error: true)
            refreshAll(); return
        }
        let alert = NSAlert(); alert.messageText = "Create a Dot"
        alert.informativeText = "Give your new ChatGPT Dot a name. Account creation limits apply."
        let name = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 26)); name.placeholderString = "Dot name"
        alert.accessoryView = name; alert.addButton(withTitle: "Create"); alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = name
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let value = name.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 80, !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
            notice("Use a name of 1–80 printable characters.", error: true); return
        }
        writing = true; notice("Creating " + value + ". Initialization may take several minutes…"); updateControls()
        // Re-read the catalog immediately before choosing first/additional.
        api.catalog { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error): self.writing = false; self.notice(error.message, error: true); self.updateControls()
            case .success(let dots):
                UserDefaults.standard.set(value, forKey: "DesktopPendingCreation")
                self.api.request("POST", "/tbo", body: ["display_name": value, "create_thread": true,
                    "create_additional": !dots.isEmpty, "should_initialize": true]) { result in
                    self.writing = false
                    switch result {
                    case .failure(let error):
                        if let code = error.status, (400..<500).contains(code), code != 408 {
                            UserDefaults.standard.removeObject(forKey: "DesktopPendingCreation")
                        }
                        self.notice(error.message, error: true)
                    case .success(let profile):
                        guard let id = profile["id"] as? String else { self.notice("Creation is unconfirmed. Refresh before trying again.", error: true); self.updateControls(); return }
                        UserDefaults.standard.removeObject(forKey: "DesktopPendingCreation")
                        UserDefaults.standard.set(id, forKey: "DesktopSelectedDot"); self.refreshAll()
                    }
                    self.updateControls()
                }
            }
        }
    }

    private func startPolling() {
        guard poll == nil, window?.isKeyWindow == true, let deadline = pollUntil, deadline > Date() else { return }
        poll = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            guard let self else { return }
            guard self.window?.isKeyWindow == true, let deadline = self.pollUntil, deadline > Date() else {
                self.stopPolling(); self.pollUntil = nil; self.notice("Refresh to check for new replies."); return
            }
            self.loadHistory()
        }
        poll?.tolerance = 1
    }
    private func stopPolling() { poll?.invalidate(); poll = nil }
    func windowDidBecomeKey(_ notification: Notification) { if !dots.isEmpty { loadHistory() }; startPolling() }
    func windowDidResignKey(_ notification: Notification) { stopPolling() }
    func windowWillClose(_ notification: Notification) { stopPolling() }
}

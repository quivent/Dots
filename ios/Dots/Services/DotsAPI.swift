import Foundation

enum APIError: LocalizedError {
    case invalidSession, invalidResponse, http(Int, Bool), deliveryUnknown, workApprovalRequired, dotPaused, connectionBusy, contextBufferReached, accountDotCreationDenied
    case localCodex(String, Bool)
    var errorDescription: String? {
        switch self {
        case .localCodex(let message, _): return message
        case .accountDotCreationDenied: return "ChatGPT refused creation of another account Dot. Existing chats still work. Open Wavesmith, Oscillator or Belle, or choose New shared chat to use your hosted agents."
        case .contextBufferReached: return "Your 10% context buffer has been reached. Save the conversation from Context before continuing elsewhere. Exporting does not reset context."
        case .connectionBusy: return "Finish sending and resolve any pending messages or Dot creation before changing connection."
        case .workApprovalRequired: return "Approve this work request before sending it."
        case .dotPaused: return "This Dot is paused. You control Resume in the chat toolbar or Dot details."
        case .invalidSession: return "Connect your ChatGPT account to continue."
        case .invalidResponse: return "ChatGPT returned an unexpected response. Refresh to check the current state."
        case .deliveryUnknown: return "The outcome could not be confirmed. Check the current state before trying again."
        case .http(let status, let writing):
            if writing && (status >= 500 || status == 408) { return "The outcome is unknown (HTTP \(status)). Refresh before trying again." }
            switch status {
            case 401: return "Your ChatGPT session expired. Reconnect in Account."
            case 403: return "ChatGPT denied this request. Check your account’s Dot access or continue in ChatGPT."
            case 404: return "This Dot or conversation is unavailable. Refresh your Dots."
            case 409: return "The Dot’s state changed. Refresh before continuing."
            case 429: return "Too many requests. Wait a moment before trying again."
            default: return "ChatGPT could not complete the request (HTTP \(status))."
            }
        }
    }
    var isUnknown: Bool {
        if case .localCodex(_, let unknown) = self { return unknown }
        if case .deliveryUnknown = self { return true }
        if case .invalidResponse = self { return true }
        if case .http(let status, let writing) = self { return writing && (status >= 500 || status == 408) }
        return false
    }
}

/// Account-backed Dots routes observed in this repository; no Mac, proxy, or Platform key.
final class DotsAPI: NSObject, URLSessionTaskDelegate {
    private var network: URLSession!
    init(configuration: URLSessionConfiguration = .ephemeral) {
        super.init()
        configuration.timeoutIntervalForRequest = 45
        configuration.timeoutIntervalForResource = 90
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        network = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // Never forward bearer credentials to a redirected origin.
    }

    static func segment(_ value: String) throws -> String {
        guard !value.isEmpty, value != ".", value != "..",
              !value.contains("/"), !value.contains("\\"), !value.contains("%"),
              value.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else {
            throw APIError.invalidResponse
        }
        guard let encoded = value.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_~"))) else {
            throw APIError.invalidResponse
        }
        return encoded
    }

    func request(_ method: String = "GET", _ path: String, account: AccountSession,
                 query: [URLQueryItem] = [], body: [String: Any]? = nil) async throws -> [String: Any] {
        guard account.isValid, path.hasPrefix("/"), !path.hasPrefix("//") else { throw APIError.invalidSession }
        if let bluetooth = account.bluetoothID, let id = UUID(uuidString: bluetooth) {
            var frame: [String: Any] = ["method": method, "path": path, "token": account.accessToken,
                                       "query": Dictionary(query.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { _, b in b })]
            if let body { frame["body"] = body }
            let response: [String: Any]
            do { response = try await BluetoothClient.shared.exchange(mac: id, frame: frame) }
            catch { throw method == "GET" ? error : APIError.deliveryUnknown }
            guard let status = response["status"] as? Int, let result = response["body"] as? [String: Any] else {
                throw method == "GET" ? APIError.invalidResponse : APIError.deliveryUnknown
            }
            guard (200..<300).contains(status) else {
                if path.contains("mac-codex-"), let message = result["error"] as? String {
                    throw APIError.localCodex(message, method != "GET" && status >= 500)
                }
                throw APIError.http(status, method != "GET")
            }
            return result
        }
        let base: String
        if let relay = account.relayURL, let url = AccountSession.validRelay(relay) {
            base = url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/v1"
        } else { base = "https://chatgpt.com/backend-api" }
        var components = URLComponents(string: base + path)!
        if !query.isEmpty { components.queryItems = query }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("Bearer " + account.accessToken, forHTTPHeaderField: "Authorization")
        if account.relayURL == nil { request.setValue(account.accountID, forHTTPHeaderField: "ChatGPT-Account-Id") }
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let writing = method != "GET"
        let data: Data
        let response: URLResponse
        do { (data, response) = try await network.data(for: request) }
        catch { throw writing ? APIError.deliveryUnknown : error }
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let failure = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            if path.contains("mac-codex-"), let message = failure?["error"] as? String {
                throw APIError.localCodex(message, writing && http.statusCode >= 500)
            }
            if failure?["error_code"] as? String == "account_dot_creation_denied" { throw APIError.accountDotCreationDenied }
            if failure?["error_code"] as? String == "work_approval_required" { throw APIError.workApprovalRequired }
            if http.statusCode == 403 && method == "POST" && path == "/tbo" { throw APIError.accountDotCreationDenied }
            throw APIError.http(http.statusCode, writing)
        }
        if data.isEmpty { return [:] }
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw writing ? APIError.deliveryUnknown : APIError.invalidResponse
        }
        return object
    }

    func collection(_ path: String, account: AccountSession, key: String = "items",
                    query: [URLQueryItem] = [], requireAccountCatalog: Bool = false) async throws -> [[String: Any]] {
        var result: [[String: Any]] = [], cursor: String?, seen = Set<String>()
        for _ in 0..<1000 {
            var parameters = query + [URLQueryItem(name: "limit", value: "25")]
            if let cursor { parameters.append(URLQueryItem(name: "cursor", value: cursor)) }
            let page = try await request("GET", path, account: account, query: parameters)
            if requireAccountCatalog {
                // The hub may return hosted chats even when its Mac/provider
                // connection is offline. That is not evidence of an empty account.
                if page["cloud_connection"] as? String == "unavailable" { throw APIError.http(503, false) }
                if page["scope"] as? String == "hosted" { throw APIError.http(403, false) }
            }
            guard let items = page[key] as? [[String: Any]] else { throw APIError.invalidResponse }
            result += items
            guard let next = page["next_cursor"] as? String ?? page["cursor"] as? String, !next.isEmpty else { return result }
            guard seen.insert(next).inserted else { throw APIError.invalidResponse }
            cursor = next
        }
        throw APIError.invalidResponse
    }

    func dots(account: AccountSession) async throws -> [Dot] {
        try await collection("/tbo", account: account,
                             query: [.init(name: "include_room_preview", value: "false")]).map(Dot.init(json:))
    }

    func profile(_ id: String, account: AccountSession) async throws -> Dot {
        let result = try await request("GET", "/tbo/" + Self.segment(id), account: account)
        return try Dot(json: result["profile"] as? [String: Any] ?? result)
    }

    func creationIsAdditional(account: AccountSession) async throws -> Bool {
        let catalog = try await collection("/tbo", account: account,
            query: [.init(name: "include_room_preview", value: "false")], requireAccountCatalog: true)
        return try catalog.map(Dot.init(json:)).contains { !$0.isHosted && !$0.isLocalCodex }
    }

    func createProfile(name: String, additional: Bool, account: AccountSession) async throws -> Dot {
        let result = try await request("POST", "/tbo", account: account, body: [
            "display_name": name, "create_thread": true, "create_additional": additional, "should_initialize": true
        ])
        let dot = try Dot(json: result)
        guard dot.threadID != nil else { throw APIError.deliveryUnknown }
        return dot
    }

    func createChat(for dot: Dot, account: AccountSession) async throws -> Dot {
        if dot.roomID != nil { return dot }
        let result = try await request("POST", "/tbo/" + Self.segment(dot.id) + "/messaging-room", account: account)
        var updated = dot
        updated.roomID = result["messaging_room_id"] as? String
        updated.threadID = result["root_thread_id"] as? String ?? dot.threadID
        guard updated.roomID?.isEmpty == false else { throw APIError.deliveryUnknown }
        return updated
    }

    func messages(room: String, before: String? = nil, account: AccountSession) async throws -> (messages: [ChatMessage], before: String?, context: ContextUsage?) {
        var query = [URLQueryItem(name: "limit", value: "25")]
        if let before { query.append(URLQueryItem(name: "before", value: before)) }
        let result = try await request("GET", "/messaging/rooms/" + Self.segment(room) + "/messages", account: account, query: query)
        guard let items = result["items"] as? [[String: Any]] else { throw APIError.invalidResponse }
        return (items.compactMap(ChatMessage.parse).sorted { $0.date < $1.date }, result["prev_cursor"] as? String,
                ContextUsage.reported(in: result))
    }

    func send(_ pending: PendingMessage, account: AccountSession) async throws -> String {
        var body: [String: Any] = [
            "content": ["text": pending.text, "attachments": []] as [String: Any],
            "request_id": pending.id, "idempotency_token": pending.id,
            "timezone_offset_min": -TimeZone.current.secondsFromGMT() / 60
        ]
        if pending.roomID.hasPrefix("hub-") || pending.roomID.hasPrefix("mac-codex-") { body["work_approved"] = pending.workApproved == true }
        let result = try await request("POST", "/messaging/rooms/" + Self.segment(pending.roomID) + "/messages", account: account, body: body)
        guard let id = result["id"] as? String, !id.isEmpty else { throw APIError.deliveryUnknown }
        return id
    }
}

struct PendingMessage: Codable, Identifiable {
    let id: String
    let roomID: String
    let text: String
    var createdAt: Date? = nil
    var workApproved: Bool? = nil
}

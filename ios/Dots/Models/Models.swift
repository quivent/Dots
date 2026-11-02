import Foundation

/// Decode only presentation fields; unknown backend fields remain outside app state.
struct Dot: Identifiable, Hashable {
    let id: String
    var name: String
    var summary: String
    var isPaused: Bool
    var roomID: String?
    var threadID: String?
    var isHosted = false
    var isLocalCodex = false
    var isCodexWorker: Bool { isLocalCodex || (isHosted && !humanOnly) }
    var memberNames: [String] = []
    var humanOnly = false
    var peopleNames: [String] = []

    init(id: String, name: String, summary: String = "", isPaused: Bool = false,
         roomID: String? = nil, threadID: String? = nil) {
        self.id = id; self.name = name; self.summary = summary
        self.isPaused = isPaused; self.roomID = roomID; self.threadID = threadID
    }

    init(json: [String: Any]) throws {
        guard let id = json["id"] as? String, !id.isEmpty else { throw APIError.invalidResponse }
        self.init(id: id, name: json["display_name"] as? String ?? "Untitled Dot",
                  summary: json["description"] as? String ?? "",
                  isPaused: json["is_paused"] as? Bool ?? false,
                  roomID: Self.identifier(json["messaging_room_id"]),
                  threadID: Self.identifier(json["active_root_thread_id"]) ?? Self.identifier(json["root_thread_id"]))
        isHosted = json["source"] as? String == "hosted"
        isLocalCodex = json["source"] as? String == "local_codex"
        memberNames = json["member_names"] as? [String] ?? []
        humanOnly = json["human_only"] as? Bool ?? false
        peopleNames = (json["people"] as? [[String: Any]] ?? []).compactMap { $0["name"] as? String }
    }

    private static func identifier(_ value: Any?) -> String? {
        guard let text = value as? String, !text.isEmpty else { return nil }
        return text
    }
}

struct ChatMessage: Identifiable, Equatable {
    let id: String
    let text: String
    let isMine: Bool
    let date: Date
    var requestID: String? = nil
    var senderName: String? = nil

    static func parse(_ json: [String: Any]) -> ChatMessage? {
        guard let id = json["id"] as? String, json["deleted_at"] == nil || json["deleted_at"] is NSNull else { return nil }
        let text: String
        let mine: Bool
        if let raw = json["raw_messages"] as? [[String: Any]] {
            text = raw.compactMap { message -> String? in
                guard let author = message["author"] as? [String: Any], author["role"] as? String == "assistant",
                      message["channel"] as? String != "analysis",
                      let content = message["content"] as? [String: Any],
                      let parts = content["parts"] as? [Any] else { return nil }
                let metadata = message["metadata"] as? [String: Any] ?? [:]
                guard metadata["is_hidden"] as? Bool != true, metadata["hidden"] as? Bool != true else { return nil }
                return parts.compactMap { $0 as? String }.joined(separator: "\n")
            }.joined(separator: "\n\n")
            mine = false
        } else if let content = json["content"] as? [String: Any], let value = content["text"] as? String {
            text = value
            let sender = json["account_user_id"] as? String
            // Dot messages can also have role=user. Their actor IDs use the
            // calpico-member namespace; presence of an ID alone does not mean us.
            mine = json["sender_is_self"] as? Bool ?? (sender != nil && sender?.hasPrefix("calpico-member") != true
                && json["role"] as? String != "assistant")
        } else { return nil }
        guard !text.isEmpty else { return nil }
        return ChatMessage(id: id, text: text, isMine: mine, date: parseDate(json["created_at"]),
                           requestID: json["request_id"] as? String ?? json["idempotency_token"] as? String,
                           senderName: mine ? nil : json["sender_display_name"] as? String)
    }
}

enum MessageFormatting {
    static func attributed(_ text: String) -> AttributedString {
        var result = (try? AttributedString(markdown: text, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        for run in result.runs {
            if let url = run.link {
                if ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") {
                    result[run.range].underlineStyle = .single
                } else { result[run.range].link = nil }
            }
        }
        return result
    }
}

struct ActivityItem: Identifiable {
    let id: String
    let title: String
    let detail: String
    let status: String
    let date: Date
    let replyOutcome: String?
    let requestID: String?
    var isActive: Bool { ["running", "in_progress", "in progress", "working", "started", "queued", "approval_needed"].contains(status.lowercased()) }

    init(json: [String: Any], index: Int) {
        id = json["id"] as? String ?? json["thread_id"] as? String ?? "item-\(index)"
        title = json["title"] as? String ?? json["name"] as? String ?? json["type"] as? String ?? "Update"
        detail = json["summary"] as? String ?? json["description"] as? String ?? json["text"] as? String ?? ""
        status = json["status"] as? String ?? ""
        date = parseDate(json["created_at"] ?? json["timestamp"])
        replyOutcome = json["reply_outcome"] as? String
        requestID = json["request_id"] as? String
    }
}

func parseDate(_ value: Any?) -> Date {
    if let seconds = value as? Double { return Date(timeIntervalSince1970: seconds) }
    guard let text = value as? String else { return .distantPast }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: text) ?? ISO8601DateFormatter().date(from: text) ?? .distantPast
}

struct AccountSession: Codable {
    let accessToken: String
    let accountID: String
    var relayURL: String? = nil
    var bluetoothID: String? = nil
    var macName: String? = nil
    var hostedOnly: Bool? = nil
    var storageID: String { accountID + (relayURL.map { "|" + $0 } ?? "") + (bluetoothID.map { "|ble:" + $0 } ?? "") }

    var isValid: Bool {
        !accessToken.isEmpty && !accountID.isEmpty && accessToken.utf8.allSatisfy { (33...126).contains($0) }
            && accountID.utf8.allSatisfy { (33...126).contains($0) }
            && (relayURL == nil || Self.validRelay(relayURL!) != nil)
            && (bluetoothID == nil || (UUID(uuidString: bluetoothID!) != nil && relayURL == nil))
    }

    static func validRelay(_ text: String) -> URL? {
        guard let parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = parts.scheme, ["https", "http"].contains(scheme), let host = parts.host?.lowercased(),
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/" else { return nil }
        if scheme == "http" {
            let components = host.split(separator: ".", omittingEmptySubsequences: false)
            let octets = components.compactMap { Int($0) }
            let ipv4 = components.count == 4 && octets.count == 4 && octets.allSatisfy { (0...255).contains($0) }
            let privateIP = ipv4 && (octets[0] == 10 || octets[0] == 127 ||
                (octets[0] == 192 && octets[1] == 168) || (octets[0] == 172 && (16...31).contains(octets[1])) ||
                (octets[0] == 100 && (64...127).contains(octets[1])))
            guard privateIP || host == "localhost" || host == "[::1]" || host == "::1" ||
                    host.hasSuffix(".ts.net") || host.hasSuffix(".local") else { return nil }
        }
        return parts.url
    }

    /// Claims select account routing only. GET /tbo verifies the actual authorization.
    static func accountID(from token: String) -> String? {
        let parts = token.split(separator: ".")
        guard parts.count == 3 else { return nil }
        var part = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        part += String(repeating: "=", count: (4 - part.count % 4) % 4)
        guard let data = Data(base64Encoded: part), let claims = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let auth = claims["https://api.openai.com/auth"] as? [String: Any] else { return nil }
        return auth["chatgpt_account_id"] as? String
    }
}

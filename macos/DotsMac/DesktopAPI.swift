import Foundation

struct DesktopDot {
    let id: String
    let name: String
    let room: String?
    let paused: Bool

    init?(_ json: [String: Any]) {
        guard let id = json["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        name = json["display_name"] as? String ?? "Untitled Dot"
        room = json["messaging_room_id"] as? String
        paused = json["is_paused"] as? Bool ?? false
    }
}

struct DesktopMessage {
    let id: String
    let text: String
    let mine: Bool
    let requestID: String?
    let created: String

    init?(_ json: [String: Any]) {
        guard let id = json["id"] as? String,
              json["deleted_at"] == nil || json["deleted_at"] is NSNull else { return nil }
        self.id = id
        requestID = json["request_id"] as? String ?? json["idempotency_token"] as? String
        created = json["created_at"] as? String ?? ""
        if let raw = json["raw_messages"] as? [[String: Any]] {
            text = raw.compactMap { message -> String? in
                let author = message["author"] as? [String: Any] ?? [:]
                let metadata = message["metadata"] as? [String: Any] ?? [:]
                guard author["role"] as? String == "assistant", message["channel"] as? String != "analysis",
                      metadata["is_hidden"] as? Bool != true, metadata["hidden"] as? Bool != true,
                      let content = message["content"] as? [String: Any],
                      let parts = content["parts"] as? [Any] else { return nil }
                return parts.compactMap { $0 as? String }.joined(separator: "\n")
            }.joined(separator: "\n\n")
            mine = false
        } else {
            let content = json["content"] as? [String: Any] ?? [:]
            text = content["text"] as? String ?? ""
            let sender = json["account_user_id"] as? String
            mine = json["sender_is_self"] as? Bool ?? (sender != nil && sender?.hasPrefix("calpico-member") != true
                && json["role"] as? String != "assistant")
        }
        guard !text.isEmpty else { return nil }
    }
}

struct DesktopError: LocalizedError {
    let message: String
    let status: Int?
    var errorDescription: String? { message }
}

final class DesktopAPI {
    private let session: URLSession
    private let tokenProvider: () -> String

    init(session: URLSession = .shared, tokenProvider: @escaping () -> String = {
        let file = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/dots/mobile-token")
        return (try? String(contentsOf: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) ?? ""
    }) { self.session = session; self.tokenProvider = tokenProvider }

    static func identifier(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_~"))) ?? ""
    }

    func request(_ method: String, _ path: String, query: [String: String] = [:], body: [String: Any]? = nil,
                 completion: @escaping (Result<[String: Any], DesktopError>) -> Void) {
        let token = tokenProvider()
        guard !token.isEmpty else {
            completion(.failure(DesktopError(message: "The Dots relay is not configured. Start it with dots mobile --install-daemon.", status: nil))); return
        }
        var components = URLComponents(string: "http://127.0.0.1:8769/v1" + path)!
        components.queryItems = query.isEmpty ? nil : query.map { URLQueryItem(name: $0.key, value: $0.value) }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.timeoutInterval = method == "POST" && path == "/tbo" ? 550 : 40
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let body {
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        // Each user action submits one request. Uncertain writes are never replayed.
        session.dataTask(with: request) { data, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let result: Result<[String: Any], DesktopError>
            if error != nil || object == nil {
                result = .failure(DesktopError(message: method == "GET"
                    ? "Could not reach the Dots relay. Check that the background service is running."
                    : "The outcome is unconfirmed. Refresh to check delivery before trying again.", status: nil))
            } else if code != 200 {
                result = .failure(DesktopError(message: object?["error"] as? String ?? "The account request was rejected.", status: code))
            } else {
                result = .success(object!)
            }
            DispatchQueue.main.async { completion(result) }
        }.resume()
    }

    func catalog(completion: @escaping (Result<[DesktopDot], DesktopError>) -> Void) {
        func page(_ cursor: String?, _ collected: [DesktopDot], _ seen: Set<String>) {
            var query = ["limit": "25", "include_room_preview": "false"]
            if let cursor { query["cursor"] = cursor }
            request("GET", "/tbo", query: query) { result in
                switch result {
                case .failure(let error): completion(.failure(error))
                case .success(let json):
                    guard let items = json["items"] as? [[String: Any]] else {
                        completion(.failure(DesktopError(message: "Unexpected Dot catalog response.", status: nil))); return
                    }
                    let dots = collected + items.compactMap(DesktopDot.init)
                    guard let next = json["cursor"] as? String, !next.isEmpty else { completion(.success(dots)); return }
                    guard !seen.contains(next), seen.count < 1000 else {
                        completion(.failure(DesktopError(message: "Dot catalog pagination did not advance.", status: nil))); return
                    }
                    page(next, dots, seen.union([next]))
                }
            }
        }
        page(nil, [], [])
    }
}

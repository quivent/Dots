import Foundation

final class Stub: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: Any]))!
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (code, json) = try Self.handler(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: json))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

func wait<T>(_ operation: (@escaping (T) -> Void) -> Void) -> T {
    var result: T?
    operation { result = $0 }
    let until = Date().addingTimeInterval(5)
    while result == nil && Date() < until { RunLoop.main.run(until: Date().addingTimeInterval(0.01)) }
    precondition(result != nil, "Request timed out")
    return result!
}

if CommandLine.arguments.contains("--live") {
    let api = DesktopAPI()
    let result: Result<[DesktopDot], DesktopError> = wait { api.catalog(completion: $0) }
    let dots = try result.get()
    print("Live desktop catalog:", dots.map(\.name).joined(separator: ", "))
    for dot in dots {
        if let room = dot.room {
            let history: Result<[String: Any], DesktopError> = wait {
                api.request("GET", "/messaging/rooms/" + DesktopAPI.identifier(room) + "/messages", query: ["limit": "25"], completion: $0)
            }
            let json = try history.get()
            guard let items = json["items"] as? [[String: Any]] else { fatalError("Invalid live history") }
            print(dot.name + ":", items.compactMap(DesktopMessage.init).count, "visible messages read; nothing sent")
        }
    }
    exit(0)
}

let config = URLSessionConfiguration.ephemeral
config.protocolClasses = [Stub.self]
let api = DesktopAPI(session: URLSession(configuration: config), tokenProvider: { "test-relay-token" })
var calls = 0
Stub.handler = { request in
    calls += 1
    precondition(request.url?.host == "127.0.0.1")
    precondition(request.value(forHTTPHeaderField: "Authorization") == "Bearer test-relay-token")
    precondition(request.value(forHTTPHeaderField: "ChatGPT-Account-Id") == nil)
    if calls == 1 { return (200, ["items": [["id": "one", "display_name": "Pocket"]], "cursor": "next"]) }
    precondition(request.url!.query!.contains("cursor=next"))
    return (200, ["items": [["id": "two", "display_name": "Other"]]])
}
let catalog: Result<[DesktopDot], DesktopError> = wait { api.catalog(completion: $0) }
precondition(try! catalog.get().map(\.name) == ["Pocket", "Other"])
precondition(calls == 2)

calls = 0
Stub.handler = { _ in calls += 1; return (200, ["items": [], "cursor": "loop"]) }
let looping: Result<[DesktopDot], DesktopError> = wait { api.catalog(completion: $0) }
if case .success = looping { fatalError("Repeated cursor must fail") }
precondition(calls == 2)

calls = 0
Stub.handler = { request in
    calls += 1
    precondition(request.httpMethod == "POST")
    return (403, ["error": "Additional Dots are not enabled for this ChatGPT account."])
}
let denied: Result<[String: Any], DesktopError> = wait { api.request("POST", "/tbo", body: [:], completion: $0) }
if case .failure(let error) = denied { precondition(error.status == 403 && error.message.contains("Additional Dots")) }
else { fatalError("Rejected creation must fail") }
precondition(calls == 1, "Creation must never be replayed")

calls = 0
Stub.handler = { _ in calls += 1; throw URLError(.timedOut) }
let uncertain: Result<[String: Any], DesktopError> = wait { api.request("POST", "/tbo", body: [:], completion: $0) }
if case .failure(let error) = uncertain { precondition(error.status == nil && error.message.contains("unconfirmed")) }
else { fatalError("Lost response must remain unconfirmed") }
precondition(calls == 1, "Uncertain write must never be replayed")

let reply = DesktopMessage(["id": "reply", "raw_messages": [
    ["author": ["role": "assistant"], "channel": "analysis", "content": ["parts": ["hidden reasoning"]]],
    ["author": ["role": "assistant"], "metadata": ["hidden": true], "content": ["parts": ["hidden"]]],
    ["author": ["role": "assistant"], "channel": "final", "content": ["parts": ["Hello"]]]
]])!
precondition(reply.text == "Hello" && !reply.mine)
precondition(DesktopMessage(["id": "deleted", "deleted_at": "today", "content": ["text": "secret"]]) == nil)
let dot = DesktopMessage(["id": "dot", "role": "user", "account_user_id": "calpico-member:one", "content": ["text": "Hello"]])!
precondition(!dot.mine)
precondition(DesktopAPI.identifier("a/b?x=1") == "a%2Fb%3Fx%3D1")
print("Desktop API checks passed: pagination, account errors, single writes, hidden-message filtering, and Dot identity.")

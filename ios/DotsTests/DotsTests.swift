import XCTest
@testable import Dots

final class MockProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: Any]))!
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, json) = try Self.handler(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: json))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

@MainActor
final class DotsTests: XCTestCase {
    func testLocalCodexUsesExistingThreadAndRequiresApprovalForOrdinaryFollowup() async throws {
        let room = "mac-codex-01a1835f-30b5-78a0-937f-a18c4ee8fadb"
        let dot = try Dot(json: ["id": room, "display_name": "Explain the work", "source": "local_codex", "messaging_room_id": room])
        XCTAssertTrue(dot.isLocalCodex)
        XCTAssertFalse(dot.isHosted)
        let store = DotsStore(api: api())
        store.dots = [dot]
        XCTAssertTrue(store.requiresApproval("How is it going?", room: room))
        MockProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/messaging/rooms/" + room + "/messages")
            let body = try self.body(request)
            XCTAssertEqual(body["work_approved"] as? Bool, true)
            XCTAssertEqual((body["content"] as? [String: Any])?["text"] as? String, "How is it going?")
            return (200, ["id": "sent"])
        }
        let relay = AccountSession(accessToken: "phone-token", accountID: "mac", relayURL: "http://127.0.0.1:8769")
        let result = try await api().send(PendingMessage(id: UUID().uuidString, roomID: room, text: "How is it going?", workApproved: true), account: relay)
        XCTAssertEqual(result, "sent")
    }

    func testHostedDiscoveryFindsOtherPhoneChatWithoutProviderOrLosingLocalState() async throws {
        let store = DotsStore(api: api())
        store.account = AccountSession(accessToken: "phone-token", accountID: "mac", relayURL: DotsStore.hostedRelay)
        let cloud = Dot(id: "cloud", name: "Pocket", roomID: "cloud-room")
        store.dots = [cloud]
        store.messages["cloud-room"] = [.init(id: "saved", text: "Keep this", isMine: true, date: .now)]
        var includeDirect = false
        var fail = false
        MockProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/hosted/rooms")
            if fail { throw URLError(.notConnectedToInternet) }
            let direct: [String: Any] = ["id": "group-hub-direct", "display_name": "Direct chat", "source": "hosted", "human_only": true, "messaging_room_id": "hub-direct"]
            return (200, ["items": includeDirect ? [direct] : []])
        }
        await store.refreshHostedRooms()
        XCTAssertEqual(store.dots.map(\.id), ["cloud"])
        includeDirect = true
        await store.refreshHostedRooms()
        XCTAssertEqual(Set(store.dots.map(\.id)), ["cloud", "group-hub-direct"])
        XCTAssertEqual(store.messages["cloud-room"]?.first?.text, "Keep this")
        fail = true
        await store.refreshHostedRooms()
        XCTAssertTrue(store.dots.contains { $0.id == "group-hub-direct" })
        XCTAssertNotNil(store.catalogSyncError)
        XCTAssertNil(store.error)
    }
    func testHumanRoomHasCorrectSenderAndNeedsNoWorkApproval() throws {
        let room = try Dot(json: ["id": "group-hub-human", "display_name": "Jay & Alex", "source": "hosted", "messaging_room_id": "hub-human", "human_only": true, "people": [["name": "Alex"]]])
        XCTAssertTrue(room.humanOnly)
        XCTAssertEqual(room.peopleNames, ["Alex"])
        let message: [String: Any] = ["id": "other", "role": "user", "account_user_id": "phone", "sender_is_self": false, "sender_display_name": "Alex", "content": ["text": "Hi"]]
        XCTAssertEqual(ChatMessage.parse(message)?.isMine, false)
        XCTAssertEqual(ChatMessage.parse(message)?.senderName, "Alex")
        let store = DotsStore(api: api())
        store.dots = [room]
        XCTAssertFalse(store.requiresApproval("Please deploy the app", room: "hub-human"))
    }
    let account = AccountSession(accessToken: "fixture-token", accountID: "fixture-account")
    func api() -> DotsAPI {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockProtocol.self]
        return DotsAPI(configuration: configuration)
    }
    override func tearDown() {
        Keychain.delete("session")
        Keychain.delete("creation-fixture-account")
        Keychain.delete("pending-fixture-account")
        MockProtocol.handler = nil
    }

    func testDirectReadUsesAccountHeadersAndFollowsPagination() async throws {
        var calls = 0
        MockProtocol.handler = { request in
            calls += 1
            XCTAssertEqual(request.url?.host, "chatgpt.com")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fixture-token")
            XCTAssertEqual(request.value(forHTTPHeaderField: "ChatGPT-Account-Id"), "fixture-account")
            XCTAssertEqual(request.httpMethod, "GET")
            if calls == 1 { return (200, ["items": [["id": "a", "display_name": "Atlas"]], "cursor": "next"]) }
            XCTAssertTrue(request.url!.query!.contains("cursor=next"))
            return (200, ["items": [["id": "b", "display_name": "Sage"]]])
        }
        let dots = try await api().dots(account: account)
        XCTAssertEqual(dots.map(\.name), ["Atlas", "Sage"])
        XCTAssertEqual(calls, 2)
    }

    func testRepeatedPaginationCursorFails() async {
        MockProtocol.handler = { _ in (200, ["items": [], "cursor": "loop"]) }
        do { _ = try await api().dots(account: account); XCTFail("Should reject a cursor loop") }
        catch { XCTAssertTrue(error is APIError) }
    }

    func testRelayUsesItsOwnTokenAndNeverSendsAccountHeader() async throws {
        let relay = AccountSession(accessToken: "mac-connection-token", accountID: "mac", relayURL: "http://100.64.1.2:8769")
        MockProtocol.handler = { request in
            XCTAssertEqual(request.url?.absoluteString, "http://100.64.1.2:8769/v1/tbo?include_room_preview=false&limit=25")
            XCTAssertNil(request.value(forHTTPHeaderField: "ChatGPT-Account-Id"))
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer mac-connection-token")
            return (200, ["items": []])
        }
        _ = try await api().dots(account: relay)
    }

    func testHostedRelaySwitchVerifiesPairedCredentialBeforeSaving() async throws {
        let store = DotsStore(api: api())
        store.account = AccountSession(accessToken: "phone-token", accountID: "mac", bluetoothID: UUID().uuidString)
        MockProtocol.handler = { request in
            XCTAssertEqual(request.url?.host, "dots.kosmos.institute")
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer phone-token")
            XCTAssertNil(request.value(forHTTPHeaderField: "ChatGPT-Account-Id"))
            return (200, ["items": [["id": "a", "display_name": "Atlas"]]])
        }
        try await store.connectHostedRelay()
        XCTAssertEqual(store.account?.relayURL, DotsStore.hostedRelay)
        XCTAssertNil(store.account?.bluetoothID)
        XCTAssertEqual(store.dots.first?.name, "Atlas")
    }

    func testHostedRelayFailureKeepsCurrentConnection() async throws {
        let store = DotsStore(api: api())
        let id = UUID().uuidString
        store.account = AccountSession(accessToken: "phone-token", accountID: "mac", bluetoothID: id)
        MockProtocol.handler = { _ in (503, [:]) }
        do { try await store.connectHostedRelay(); XCTFail("Must verify before switching") } catch {}
        XCTAssertEqual(store.account?.bluetoothID, id)
        XCTAssertNil(store.account?.relayURL)
    }

    func testHostedRelayDoesNotForwardProviderLogin() async {
        let store = DotsStore(api: api())
        store.account = account
        MockProtocol.handler = { _ in XCTFail("Provider token must never be sent to the relay"); return (200, [:]) }
        do { try await store.connectHostedRelay(); XCTFail() } catch {}
    }

    func testContextReserveBlocksNewSendAndRetryWithoutDiscardingPending() async {
        let store = DotsStore(api: api())
        store.isDemo = true
        store.contextUsage["room"] = .init(used: 899_900, limit: 1_000_000)
        XCTAssertTrue(store.enqueue("Hello", room: "room"))
        let identity = store.pending["room"]?.id
        store.contextUsage["room"] = .init(used: 900_000, limit: 1_000_000)
        await store.retryMessage("room")
        XCTAssertEqual(store.pending["room"]?.id, identity)
        XCTAssertTrue(store.messages["room", default: []].isEmpty)
        XCTAssertNotNil(store.error)
        store.contextUsage["new-room"] = .init(used: 900_000, limit: 1_000_000)
        XCTAssertFalse(store.enqueue("Hello", room: "new-room"))
        XCTAssertNil(store.pending["new-room"])
    }

    func testOnlyPrivateHTTPRelayAddressesAreAccepted() {
        for value in ["http://100.64.0.1:8769", "http://192.168.1.3:8769", "http://mac.local:8769", "https://relay.example.com"] {
            XCTAssertNotNil(AccountSession.validRelay(value), value)
        }
        for value in ["http://example.com", "http://100.63.0.1", "http://192.168.1.1.evil.com", "https://user:password@example.com", "https://example.com/other", "file:///tmp"] {
            XCTAssertNil(AccountSession.validRelay(value), value)
        }
    }

    func testCreationAndRoomCreationAreDifferentWrites() async throws {
        var paths: [String] = []
        MockProtocol.handler = { request in
            paths.append(request.url!.path)
            if request.url!.path == "/backend-api/tbo" {
                let body = try self.body(request)
                XCTAssertEqual(body["create_thread"] as? Bool, true)
                XCTAssertEqual(body["should_initialize"] as? Bool, true)
                return (200, ["id": "new", "display_name": "Scout", "root_thread_id": "thread"])
            }
            return (200, ["messaging_room_id": "room"])
        }
        let client = api()
        let dot = try await client.createProfile(name: "Scout", additional: true, account: account)
        XCTAssertNil(dot.roomID)
        XCTAssertEqual(paths.count, 1)
        let updated = try await client.createChat(for: dot, account: account)
        XCTAssertEqual(updated.roomID, "room")
        XCTAssertEqual(paths, ["/backend-api/tbo", "/backend-api/tbo/new/messaging-room"])
    }

    func testIncompleteCreationIsNotReportedAsReady() async {
        MockProtocol.handler = { _ in (200, ["id": "new", "display_name": "Scout"]) }
        do {
            _ = try await api().createProfile(name: "Scout", additional: true, account: account)
            XCTFail("Missing root thread must leave creation unconfirmed")
        } catch { XCTAssertTrue((error as? APIError)?.isUnknown == true) }
    }

    func testExistingRoomIsOpenedWithoutAnotherCreationWrite() async throws {
        var writes = 0
        MockProtocol.handler = { request in
            if request.httpMethod == "POST" { writes += 1 }
            if request.url?.path == "/backend-api/tbo" { return (200, ["items": [["id": "existing", "display_name": "Atlas"]]]) }
            return (200, ["id": "existing", "display_name": "Atlas", "root_thread_id": "thread", "messaging_room_id": "room"])
        }
        let store = DotsStore(api: api())
        try await store.connect(account)
        let updated = try await store.createChat(dot: store.dots[0])
        XCTAssertEqual(updated.roomID, "room")
        XCTAssertEqual(writes, 0)
    }

    func testCreationWithUnknownOutcomeIsNotRetried() async throws {
        var writes = 0
        MockProtocol.handler = { request in
            if request.httpMethod == "GET" { return (200, ["items": []]) }
            writes += 1
            return (503, [:])
        }
        let store = DotsStore(api: api())
        try await store.connect(account)
        do { _ = try await store.create(name: "Scout"); XCTFail() } catch {}
        XCTAssertTrue(store.uncertainCreation)
        do { _ = try await store.create(name: "Scout"); XCTFail() } catch {}
        XCTAssertEqual(writes, 1)
    }

    func testHostedCatalogDoesNotMakeFirstAccountDotAdditional() async throws {
        var writes = 0
        MockProtocol.handler = { request in
            if request.httpMethod == "GET" {
                return (200, ["items": [["id": "hosted-wavesmith", "source": "hosted"]]])
            }
            writes += 1
            XCTAssertEqual(try self.body(request)["create_additional"] as? Bool, false)
            return (200, ["id": "new", "display_name": "Scout", "root_thread_id": "thread"])
        }
        let store = DotsStore(api: api()); store.account = account
        store.dots = [try Dot(json: ["id": "hosted-wavesmith", "source": "hosted"])]
        _ = try await store.create(name: "Scout")
        XCTAssertEqual(writes, 1)
    }

    func testCreationRefreshesAnEmptyVisibleCatalogBeforeChoosingFlag() async throws {
        MockProtocol.handler = { request in
            if request.httpMethod == "GET" { return (200, ["items": [["id": "existing", "display_name": "Pocket"]]]) }
            XCTAssertEqual(try self.body(request)["create_additional"] as? Bool, true)
            return (200, ["id": "new", "display_name": "Scout", "root_thread_id": "thread"])
        }
        let store = DotsStore(api: api()); store.account = account; store.dots = []
        _ = try await store.create(name: "Scout")
    }

    func testUnavailableProviderCatalogDoesNotWriteOrLeaveCreationUncertain() async throws {
        var writes = 0
        MockProtocol.handler = { request in
            if request.httpMethod == "POST" { writes += 1 }
            return (200, ["items": [["id": "hosted-belle", "source": "hosted"]], "cloud_connection": "unavailable"])
        }
        let store = DotsStore(api: api()); store.account = account
        do { _ = try await store.create(name: "Scout"); XCTFail("Provider discovery must succeed first") }
        catch { XCTAssertFalse((error as? APIError)?.isUnknown ?? true) }
        XCTAssertFalse(store.uncertainCreation)
        XCTAssertEqual(writes, 0)
        XCTAssertNil(Keychain.read("creation-" + account.storageID))
    }

    func testExplicitMessageRetryReusesIdempotencyToken() async throws {
        var ids: [String] = []
        MockProtocol.handler = { request in
            if request.httpMethod == "GET" { return (200, ["items": []]) }
            let body = try self.body(request)
            let id = try XCTUnwrap(body["request_id"] as? String)
            XCTAssertEqual(id, body["idempotency_token"] as? String)
            ids.append(id)
            return ids.count == 1 ? (503, [:]) : (200, ["id": "accepted-message"])
        }
        let store = DotsStore(api: api())
        try await store.connect(account)
        await store.send("Hello", room: "room")
        XCTAssertNotNil(store.pending["room"])
        XCTAssertEqual(ids.count, 1)
        await store.retryMessage("room")
        XCTAssertEqual(ids.count, 2)
        XCTAssertEqual(ids[0], ids[1])
        XCTAssertNil(store.pending["room"])
    }

    func testHiddenAssistantContentAndAnalysisAreNeverRendered() {
        let item: [String: Any] = ["id": "reply", "created_at": "2026-10-20T12:00:00Z", "raw_messages": [
            ["author": ["role": "assistant"], "channel": "analysis", "content": ["parts": ["private reasoning"]]],
            ["author": ["role": "assistant"], "metadata": ["is_hidden": true], "content": ["parts": ["hidden"]]],
            ["author": ["role": "assistant"], "channel": "final", "content": ["parts": ["Visible answer"]]]
        ]]
        XCTAssertEqual(ChatMessage.parse(item)?.text, "Visible answer")
        XCTAssertEqual(ChatMessage.parse(item)?.isMine, false)
    }

    func testDotActorIsNotMistakenForTheUserDespiteUserRole() {
        let dot: [String: Any] = ["id": "dot", "role": "user", "account_user_id": "calpico-member-fixture",
                                  "content": ["text": "Hello from your Dot"]]
        let user: [String: Any] = ["id": "user", "role": "user", "account_user_id": "user-fixture",
                                   "content": ["text": "Hello"]]
        XCTAssertEqual(ChatMessage.parse(dot)?.isMine, false)
        XCTAssertEqual(ChatMessage.parse(user)?.isMine, true)
    }

    func testMarkdownLinksRetainTheirDestinationWithoutShowingMarkup() {
        let value = MessageFormatting.attributed("Read [the guide](https://example.com/guide).\n\n**Keep this.**")
        XCTAssertEqual(String(value.characters), "Read the guide.\n\nKeep this.")
        XCTAssertTrue(value.runs.contains { $0.link?.absoluteString == "https://example.com/guide" })
        XCTAssertFalse(MessageFormatting.attributed("[bad](javascript:alert)").runs.contains { $0.link != nil })
    }

    func testEnqueuePersistsImmediatelyAndDoesNotOverwriteAnUnconfirmedSend() throws {
        let store = DotsStore(api: api())
        store.account = account
        XCTAssertTrue(store.enqueue("First", room: "room"))
        let firstID = try XCTUnwrap(store.pending["room"]?.id)
        XCTAssertNotNil(store.pending["room"]?.createdAt)
        XCTAssertNotNil(Keychain.read("pending-fixture-account"))
        XCTAssertFalse(store.enqueue("Second", room: "room"))
        XCTAssertEqual(store.pending["room"]?.id, firstID)
        XCTAssertEqual(store.pending["room"]?.text, "First")
    }

    func testPausedDotBlocksMessagesAndUserCanResumeThroughProvider() async throws {
        let store = DotsStore(api: api())
        store.account = account
        let dot = Dot(id: "paused", name: "Pocket", isPaused: true, roomID: "room")
        store.dots = [dot]
        var methods: [String] = []
        MockProtocol.handler = { request in
            methods.append(request.httpMethod ?? "")
            if request.httpMethod == "POST" {
                XCTAssertTrue(request.url!.path.hasSuffix("/runtime/resume"))
                return (200, ["status": "applied"])
            }
            return (200, ["id": "paused", "display_name": "Pocket", "is_paused": false, "messaging_room_id": "room"])
        }
        XCTAssertFalse(store.enqueue("Run work", room: "room"))
        store.pending["room"] = PendingMessage(id: UUID().uuidString, roomID: "room", text: "Previous draft")
        await store.retryMessage("room")
        XCTAssertNotNil(store.pending["room"])
        XCTAssertTrue(methods.isEmpty)
        try await store.runtime("resume", dot: dot)
        XCTAssertEqual(methods, ["POST", "GET"])
        XCTAssertEqual(store.dots.first?.isPaused, false)
    }

    func testWorkRequestRequiresApprovalAndRetryKeepsTheSameScopedGrant() {
        let store = DotsStore(api: api()); store.account = account
        XCTAssertFalse(store.enqueue("Implement Bluetooth", room: "room"))
        XCTAssertNil(store.pending["room"])
        XCTAssertTrue(store.enqueue("Implement Bluetooth", room: "room", approveWork: true))
        let original = store.pending["room"]!
        XCTAssertTrue(original.workApproved == true)
        XCTAssertFalse(store.approvePendingWork("different-id", room: "room"))
        XCTAssertEqual(store.pending["room"]?.id, original.id)
        XCTAssertEqual(store.pending["room"]?.text, "Implement Bluetooth")
        XCTAssertTrue(store.enqueue("Research GLM results", room: "other-room"))
        XCTAssertEqual(store.pending["other-room"]?.workApproved, false)
    }

    func testHostedConversationNeedsApprovalAndPreservesMemberIdentity() throws {
        let store = DotsStore(api: api()); store.account = account
        XCTAssertFalse(store.enqueue("Hello", room: "hub-wavesmith"))
        XCTAssertNil(store.pending["hub-wavesmith"])
        XCTAssertTrue(store.enqueue("Hello", room: "hub-wavesmith", approveWork: true))
        XCTAssertEqual(store.pending["hub-wavesmith"]?.workApproved, true)
        XCTAssertTrue(store.enqueue("Hello", room: "cloud-room"))
        let dot = try Dot(json: ["id": "hosted-wavesmith", "source": "hosted", "member_names": ["Wavesmith"]])
        XCTAssertTrue(dot.isHosted)
        XCTAssertEqual(dot.memberNames, ["Wavesmith"])
        let message = ChatMessage.parse(["id": "reply", "role": "assistant", "content": ["text": "Hello"], "sender_display_name": "Belle"])
        XCTAssertEqual(message?.senderName, "Belle")
        XCTAssertEqual(message?.isMine, false)
    }

    func testResearchEntryPreservesSourcesAndRejectsUnsafeLinks() throws {
        let entry = try ResearchEntry(json: ["id": "entry-1", "title": "Research", "synthesis": "Findings",
            "author": "Belle", "tags": ["waves"], "uncertainty": "Preliminary", "sources": [
                ["title": "Study", "url": "https://example.org/study"],
                ["title": "Unsafe", "url": "file:///etc/passwd"]]])
        XCTAssertEqual(entry.sources.count, 1)
        XCTAssertEqual(entry.author, "Belle")
        XCTAssertTrue(entry.shareText.contains("Findings"))
        XCTAssertTrue(entry.shareText.contains("https://example.org/study"))
        XCTAssertTrue(entry.shareText.contains("Preliminary"))
        XCTAssertFalse(entry.shareText.contains("file:///"))
    }

    func testPollingPreservesLoadedEarlierMessagesAndReadFailuresStayInline() async throws {
        var count = 0
        MockProtocol.handler = { request in
            if !request.url!.path.hasSuffix("/messages") { return (200, ["items": []]) }
            count += 1
            if count == 4 { return (503, [:]) }
            let id = count == 2 ? "older" : "latest"
            return (200, ["items": [["id": id, "content": ["text": id], "account_user_id": "user-fixture"]],
                          "prev_cursor": count == 2 ? NSNull() : "previous" as Any])
        }
        let store = DotsStore(api: api())
        try await store.connect(account)
        await store.loadMessages("room")
        await store.loadMessages("room", older: true)
        await store.loadMessages("room")
        XCTAssertEqual(Set(store.messages["room", default: []].map(\.id)), ["older", "latest"])
        XCTAssertNil(store.olderCursors["room"])
        await store.loadMessages("room")
        XCTAssertNotNil(store.chatErrors["room"])
        XCTAssertNil(store.error)
    }

    func testHistoryCanConfirmAnUnacknowledgedMessageWithoutResending() async throws {
        var requestID = ""
        var writes = 0
        MockProtocol.handler = { request in
            if request.httpMethod == "POST" {
                writes += 1
                requestID = try self.body(request)["request_id"] as! String
                return (503, [:])
            }
            if request.url!.path.hasSuffix("/messages") {
                let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems
                XCTAssertEqual(query?.first(where: { $0.name == "limit" })?.value, "25")
                return (200, ["items": [["id": "accepted", "request_id": requestID,
                    "account_user_id": "user", "content": ["text": "Hello"]]]])
            }
            return (200, ["items": []])
        }
        let store = DotsStore(api: api())
        try await store.connect(account)
        await store.send("Hello", room: "room")
        XCTAssertNotNil(store.pending["room"])
        await store.loadMessages("room")
        XCTAssertNil(store.pending["room"])
        XCTAssertEqual(store.messages["room"]?.first?.text, "Hello")
        XCTAssertEqual(writes, 1)
    }

    func testUnsafeRouteIdentifiersAreRejected() {
        for value in ["../one", "one/two", "%2F", "..", "", "line\nbreak"] {
            XCTAssertThrowsError(try DotsAPI.segment(value))
        }
    }

    nonisolated private func body(_ request: URLRequest) throws -> [String: Any] {
        if let data = request.httpBody { return try JSONSerialization.jsonObject(with: data) as! [String: Any] }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open(); defer { stream.close() }
        var data = Data(), bytes = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&bytes, maxLength: bytes.count)
            if count <= 0 { break }
            data.append(contentsOf: bytes.prefix(count))
        }
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
}

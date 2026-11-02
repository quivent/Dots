import XCTest
@testable import Dots

final class ConnectionUsageTests: XCTestCase {
    func testFramesSurviveEveryPacketBoundaryAndMultipleFrames() throws {
        let one = try BluetoothWire.encode(["id": "one", "text": "Unicode 🐈 and a newline\nmore text"])
        let two = try BluetoothWire.encode(["id": "two", "status": 200])
        let bytes = one + two
        for size in 1...bytes.count {
            var receiver = BluetoothFrames(limit: 65_536)
            var received: [[String: Any]] = []
            for offset in stride(from: 0, to: bytes.count, by: size) {
                received += try receiver.append(Data(bytes[offset..<min(bytes.count, offset + size)]))
            }
            XCTAssertEqual(received.count, 2)
            XCTAssertEqual(received[0]["text"] as? String, "Unicode 🐈 and a newline\nmore text")
            XCTAssertEqual(received[1]["id"] as? String, "two")
        }
    }
    func testOversizedAndMalformedFramesFailClosed() {
        var receiver = BluetoothFrames(limit: 8)
        XCTAssertThrowsError(try receiver.append(Data(repeating: 65, count: 9)))
        XCTAssertThrowsError(try receiver.append(Data("oops\n".utf8)))
    }
    func testLifetimeTokensAreNotMistakenForContextUsage() {
        XCTAssertNil(ContextUsage.reported(in: ["usage": ["total_tokens": 999_999]]))
        XCTAssertNil(ContextUsage.reported(in: ["context_usage": ["used_tokens": -1, "max_tokens": 1_000_000]]))
        let usage = ContextUsage.reported(in: ["context_usage": ["used_tokens": 850_000, "max_tokens": 1_000_000]])
        XCTAssertEqual(usage?.used, 850_000)
        XCTAssertFalse(usage?.nearLimit == true)
        XCTAssertTrue(ContextUsage(used: 900_000, limit: 1_000_000).nearLimit)
    }
    func testContextBufferHonorsPlanningTargetAndSmallerProviderWindow() {
        let planned = ContextBudget(reported: .init(used: 900_000, limit: 1_050_000), messages: [])
        XCTAssertEqual(planned.limit, 1_000_000)
        XCTAssertEqual(planned.reserve, 100_000)
        XCTAssertTrue(planned.bufferReached)
        let smaller = ContextBudget(reported: .init(used: 230_400, limit: 256_000), messages: [])
        XCTAssertEqual(smaller.sendLimit, 230_400)
        XCTAssertTrue(smaller.bufferReached)
        let before = ContextBudget(reported: .init(used: 899_990, limit: 1_000_000), messages: [])
        XCTAssertFalse(before.wouldEnterReserve(adding: "Hi"))
        XCTAssertTrue(before.wouldEnterReserve(adding: String(repeating: "x", count: 40)))
        let unknown = ContextBudget(reported: nil, messages: [])
        XCTAssertTrue(unknown.isEstimated)
        XCTAssertEqual(unknown.limit, 1_000_000)
    }
    func testCreditNoticeIsAnIntentEstimate() {
        XCTAssertEqual(WorkNotice.assess("How are you?"), .conversation)
        XCTAssertEqual(WorkNotice.assess("Implement Bluetooth in the iOS app"), .possibleCoding)
        XCTAssertEqual(WorkNotice.assess("Research the latest results"), .conversation)
        XCTAssertEqual(WorkNotice.assess("Search for the GLM benchmark"), .conversation)
        XCTAssertEqual(WorkNotice.assess("What does deploy mean?"), .conversation)
        XCTAssertEqual(WorkNotice.assess("Start a background research job"), .possibleTools)
        XCTAssertEqual(WorkNotice.assess("Please send an email to Sam"), .possibleTools)
    }
    func testBluetoothSessionHasItsOwnStorageScope() {
        let id = UUID().uuidString
        let bluetooth = AccountSession(accessToken: "phone-token", accountID: "mac", bluetoothID: id)
        XCTAssertTrue(bluetooth.isValid)
        XCTAssertNotEqual(bluetooth.storageID, AccountSession(accessToken: "phone-token", accountID: "mac", relayURL: "http://mac.local:8769").storageID)
        XCTAssertFalse(AccountSession(accessToken: "phone-token", accountID: "mac", bluetoothID: "not-a-uuid").isValid)
        XCTAssertFalse(AccountSession(accessToken: "phone-token", accountID: "mac", relayURL: "http://mac.local:8769", bluetoothID: id).isValid)
    }
}

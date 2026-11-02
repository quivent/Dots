import XCTest

final class DotsUITests: XCTestCase {
    func testPhysicalDirectChatAppearsWithoutManualRefresh() throws {
        guard ProcessInfo.processInfo.environment["DOTS_VERIFY_LIVE_DISCOVERY"] == "1" else {
            throw XCTSkip("Requires the existing shared Direct chat; reads only.")
        }
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Chats"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Chats"].tap()
        XCTAssertTrue(app.staticTexts["Direct chat"].firstMatch.waitForExistence(timeout: 10), app.debugDescription)
        capture(app, "Direct chat discovered without refresh")
    }
    func testPhysicalPeoplePickerCreatesEmptyDirectChat() throws {
        guard let person = ProcessInfo.processInfo.environment["DOTS_VERIFY_PERSON_CHAT"] else {
            throw XCTSkip("Requires both invited phones; creates an empty room and sends no messages.")
        }
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Chats"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Chats"].tap()
        app.buttons["new-dot"].tap(); app.buttons["New chat"].tap()
        let participant = app.switches["person-" + person]
        XCTAssertTrue(participant.waitForExistence(timeout: 20), app.debugDescription)
        app.textFields["Chat name (optional)"].tap()
        app.textFields["Chat name (optional)"].typeText("Direct chat\n")
        participant.tap()
        capture(app, "People picker with optional Dots")
        app.buttons["create-people-chat"].tap()
        XCTAssertTrue(app.navigationBars["Direct chat"].waitForExistence(timeout: 20), app.debugDescription)
        XCTAssertTrue(app.buttons["credit-notice"].label.contains("Just people"))
        XCTAssertFalse(app.buttons["runtime-control"].exists)
        XCTAssertFalse(app.otherElements["waiting-for-reply"].exists)
        capture(app, "One to one chat without agent work")
    }
    func testPhysicalNearbyInvitationHandoff() throws {
        guard ProcessInfo.processInfo.environment["DOTS_VERIFY_NEARBY_INVITE"] == "1" else {
            throw XCTSkip("Requires Joshy and a nearby Android joining over Bluetooth. Starts no agent turns.")
        }
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Account"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Account"].tap()
        let invite = app.buttons["invite-server-phone"].firstMatch
        XCTAssertTrue(invite.waitForExistence(timeout: 10)); invite.tap()
        let nearby = app.buttons["invite-nearby"].firstMatch
        XCTAssertTrue(nearby.waitForExistence(timeout: 10)); nearby.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for _ in 0..<90 {
            if app.alerts["Let this nearby phone join?"].exists { break }
            for title in ["Allow", "Pair", "OK"] {
                let button = springboard.alerts.buttons[title].firstMatch
                if button.exists { button.tap() }
            }
            Thread.sleep(forTimeInterval: 1)
        }
        let approval = app.alerts["Let this nearby phone join?"]
        XCTAssertTrue(approval.exists, app.debugDescription)
        capture(app, "Nearby invitation requires owner approval")
        approval.buttons["Allow"].tap()
        XCTAssertTrue(app.staticTexts["Invitation sent. The other phone will connect to your server."].waitForExistence(timeout: 10), app.debugDescription)
        capture(app, "Nearby invitation sent")
    }

    func testPhysicalResearchBank() throws {
        guard ProcessInfo.processInfo.environment["DOTS_VERIFY_BANK"] == "1" else {
            throw XCTSkip("Requires Joshy connected to the hosted server; read only.")
        }
        let app = XCUIApplication(); app.launch()
        let bank = app.tabBars.buttons["Bank"]
        XCTAssertTrue(bank.waitForExistence(timeout: 20)); bank.tap()
        XCTAssertTrue(app.navigationBars["Bank"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Your research bank"].waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertFalse(app.staticTexts["Couldn’t load the Bank. Pull down to retry."].exists)
        capture(app, "Shared research Bank")
    }
    func testPhysicalHostedMembersAndApprovalCancel() throws {
        guard ProcessInfo.processInfo.environment["DOTS_VERIFY_HOSTED"] == "1" else {
            throw XCTSkip("Requires Joshy connected to the hosted server; sends no messages.")
        }
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Chats"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Chats"].tap()
        let wavesmith = app.buttons["dot-hosted-wavesmith"].firstMatch
        XCTAssertTrue(wavesmith.waitForExistence(timeout: 30), app.debugDescription)
        XCTAssertTrue(app.buttons["dot-hosted-oscillator"].firstMatch.exists)
        XCTAssertTrue(app.buttons["dot-hosted-belle"].firstMatch.exists)
        capture(app, "Hosted agents and shared chat")
        wavesmith.tap()
        let draft = app.descendants(matching: .any)["message-draft"].firstMatch
        XCTAssertTrue(draft.waitForExistence(timeout: 10))
        draft.tap(); draft.typeText("Hello")
        app.buttons["Send message"].tap()
        XCTAssertTrue(app.navigationBars["Approve work request"].waitForExistence(timeout: 5))
        capture(app, "Hosted turn requires approval")
        app.buttons["Cancel"].firstMatch.tap()
        XCTAssertEqual(draft.value as? String, "Hello")
        XCTAssertFalse(app.staticTexts["You: Hello"].exists)
    }
    func testPhysicalConnectHostedRelay() throws {
        guard ProcessInfo.processInfo.environment["DOTS_CONNECT_HOSTED"] == "1" else {
            throw XCTSkip("Requires a paired physical phone; changes its selected transport.")
        }
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Account"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Account"].tap()
        let connect = app.buttons["connect-hosted-relay"].firstMatch
        if connect.waitForExistence(timeout: 10) {
            expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: connect)
            waitForExpectations(timeout: 30)
            connect.tap()
        }
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Dots server · HTTPS")).firstMatch.waitForExistence(timeout: 35), app.debugDescription)
        app.tabBars.buttons["Dots"].tap()
        XCTAssertTrue(app.buttons["new-dot"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.alerts["Couldn’t complete the request"].exists)
        capture(app, "Connected through public HTTPS relay")
    }
    func testResearchIsOrdinaryChatAndWorkWaitsForApproval() {
        let app = preview()
        app.buttons["dot-atlas"].tap()
        let draft = app.descendants(matching: .any)["message-draft"].firstMatch
        draft.tap(); draft.typeText("Research the latest GLM results")
        app.buttons["Send message"].tap()
        XCTAssertTrue(app.staticTexts["You: Research the latest GLM results"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.navigationBars["Approve work request"].exists)
        draft.tap(); draft.typeText("Implement Bluetooth")
        app.buttons["Send message"].tap()
        XCTAssertTrue(app.navigationBars["Approve work request"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["You: Implement Bluetooth"].exists)
        app.buttons["Cancel"].tap()
        XCTAssertEqual(draft.value as? String, "Implement Bluetooth")
        app.buttons["Send message"].tap()
        app.buttons["approve-work-request"].tap()
        XCTAssertTrue(app.staticTexts["You: Implement Bluetooth"].waitForExistence(timeout: 5))
        capture(app, "Approved request sent")
    }

    func testUserControlsPauseAndResume() {
        let app = preview()
        app.buttons["dot-atlas"].tap()
        app.buttons["runtime-control"].tap()
        let confirm = app.buttons["confirm-runtime-change"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        XCTAssertTrue(app.staticTexts["Paused on provider"].waitForExistence(timeout: 5))
        app.buttons["runtime-control"].tap()
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.staticTexts["Paused on provider"])
        waitForExpectations(timeout: 5)
        XCTAssertEqual(app.buttons["runtime-control"].label, "Pause Dot")
    }
    func testPhysicalPausedControlsDoNotResumeWithoutConfirmation() throws {
        guard ProcessInfo.processInfo.environment["DOTS_VERIFY_CONTROLS"] == "1" else {
            throw XCTSkip("Requires paired Joshy and paused Pocket.")
        }
        let app = XCUIApplication(); app.launch()
        let chat = app.buttons.containing(.staticText, identifier: "Pocket").firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 30)); chat.tap()
        XCTAssertTrue(app.staticTexts["Paused on provider"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["runtime-control"].isEnabled)
        XCTAssertEqual(app.buttons["runtime-control"].label, "Resume Dot")
        app.buttons["runtime-control"].tap()
        XCTAssertTrue(app.buttons["confirm-runtime-change"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Paused on provider"].exists)
        capture(app, "User controls paused Pocket")
    }
    func testPhysicalExistingChatPolish() throws {
        guard let name = ProcessInfo.processInfo.environment["DOTS_VERIFY_CHAT"] else {
            throw XCTSkip("Requires a paired physical phone and an existing conversation.")
        }
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Chats"].waitForExistence(timeout: 15))
        let chat = app.buttons.containing(.staticText, identifier: name).firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 30), app.debugDescription)
        chat.tap()
        let dot = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Dot: ")).firstMatch
        let user = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "You: ")).firstMatch
        XCTAssertTrue(dot.waitForExistence(timeout: 30), app.debugDescription)
        XCTAssertTrue(user.exists)
        XCTAssertGreaterThan(user.frame.minX, dot.frame.minX)
        XCTAssertFalse(app.alerts["Couldn’t complete the request"].exists)
        capture(app, "Live chat with separate senders")
        app.buttons["context-details"].tap()
        XCTAssertTrue(app.buttons["view-conversation-text"].waitForExistence(timeout: 5))
        capture(app, "Live context controls")
        app.buttons["Done"].tap()
    }
    func testChatBubblesLinksComposerAndContextControls() {
        let app = preview()
        app.buttons["dot-atlas"].tap()
        let mine = app.staticTexts["bubble-a"]
        let theirs = app.staticTexts["bubble-b"]
        XCTAssertTrue(mine.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(mine.frame.minX, theirs.frame.minX)
        XCTAssertTrue(app.staticTexts["bubble-c"].label.contains("OpenAI documentation"))
        XCTAssertFalse(app.staticTexts["bubble-c"].label.contains("](https:"))
        app.buttons["context-details"].tap()
        XCTAssertTrue(app.buttons["view-conversation-text"].waitForExistence(timeout: 5))
        app.buttons["view-conversation-text"].tap()
        XCTAssertTrue(app.navigationBars["Conversation text"].waitForExistence(timeout: 5))
        app.navigationBars.buttons.element(boundBy: 0).tap()
        app.buttons["Done"].tap()
        let draft = app.descendants(matching: .any)["message-draft"].firstMatch
        draft.tap(); draft.typeText("A quick message")
        app.buttons["Send message"].tap()
        XCTAssertTrue(app.staticTexts["You: A quick message"].waitForExistence(timeout: 5))
        let visible = NSPredicate(format: "hittable == true")
        expectation(for: visible, evaluatedWith: app.staticTexts["You: A quick message"])
        waitForExpectations(timeout: 5)
        XCTAssertNotEqual(draft.value as? String, "A quick message")
        capture(app, "Chat polish with keyboard")
    }
    func testPhysicalCreateRequestedDotAndOpenChat() throws {
        guard let name = ProcessInfo.processInfo.environment["DOTS_CREATE_NAME"], !name.isEmpty else {
            throw XCTSkip("Creates a real Dot only when explicitly requested.")
        }
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Dots"].waitForExistence(timeout: 15))
        app.tabBars.buttons["Dots"].tap()
        let refresh = app.navigationBars.buttons["Refresh"]
        expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: refresh)
        waitForExpectations(timeout: 40)
        XCTAssertFalse(app.alerts["Couldn’t complete the request"].exists, app.debugDescription)
        let existing = app.buttons.containing(.staticText, identifier: name).firstMatch
        if existing.exists {
            existing.tap()
            if app.buttons["setup-chat"].exists { app.buttons["setup-chat"].tap() }
            else if app.buttons["open-chat"].exists { app.buttons["open-chat"].tap() }
        } else {
            app.buttons["new-dot"].tap()
            let field = app.textFields["dot-name"]
            XCTAssertTrue(field.waitForExistence(timeout: 5))
            field.tap(); field.typeText(name)
            app.buttons["setup-create-dot"].tap()
        }
        if !app.descendants(matching: .any)["message-draft"].firstMatch.exists {
            let ready = NSPredicate { _, _ in
                app.buttons["setup-open-chat"].exists || app.buttons["setup-create-chat"].exists
            }
            expectation(for: ready, evaluatedWith: app)
            waitForExpectations(timeout: 100)
            if app.buttons["setup-create-chat"].exists { app.buttons["setup-create-chat"].tap() }
            XCTAssertTrue(app.buttons["setup-open-chat"].waitForExistence(timeout: 100), app.debugDescription)
            app.buttons["setup-open-chat"].tap()
        }
        XCTAssertTrue(app.descendants(matching: .any)["message-draft"].firstMatch.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.navigationBars[name].exists)
        let message = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@ OR label BEGINSWITH %@", "You: ", "Dot: ")).firstMatch
        XCTAssertTrue(message.waitForExistence(timeout: 40), app.debugDescription)
        XCTAssertFalse(app.alerts["Couldn’t complete the request"].exists)
        capture(app, "Requested Dot ready on phone")
    }
    func testPhysicalSavedMacReconnect() throws {
        guard ProcessInfo.processInfo.environment["DOTS_TEST_RECONNECT"] == "1" else {
            throw XCTSkip("Requires an already-paired physical phone.")
        }
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["Account"].waitForExistence(timeout: 15))
        // Wait until the catalog refresh finishes, then reject a connection error.
        let busy = app.activityIndicators.firstMatch
        if busy.exists {
            expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: busy)
            waitForExpectations(timeout: 40)
        }
        XCTAssertFalse(app.alerts["Couldn’t complete the request"].exists, app.debugDescription)
    }
    func testPhysicalMacBluetoothPairing() throws {
        guard let code = ProcessInfo.processInfo.environment["DOTS_TEST_PAIRING_CODE"] else {
            throw XCTSkip("Requires a fresh code and a physical phone near Dots Mac.")
        }
        let app = XCUIApplication()
        app.launch()
        app.buttons["Connect through your Mac"].tap()
        let mac = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "nearby-mac-")).firstMatch
        XCTAssertTrue(mac.waitForExistence(timeout: 25), app.debugDescription)
        mac.tap()
        let field = app.textFields["pairing-code"]
        field.tap(); field.typeText(code)
        app.buttons["pair-mac"].tap()
        XCTAssertTrue(app.tabBars.buttons["Account"].waitForExistence(timeout: 100), app.debugDescription)
    }
    override func setUpWithError() throws { continueAfterFailure = false }
    private func preview(_ arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-demo"] + arguments
        app.launch()
        return app
    }
    private func capture(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    func testExistingChatCanSendWithoutCreatingAnotherDot() {
        let app = preview()
        XCTAssertTrue(app.buttons["dot-atlas"].waitForExistence(timeout: 10))
        capture(app, "Chats")
        app.buttons["dot-atlas"].tap()
        let draft = app.descendants(matching: .any)["message-draft"].firstMatch
        XCTAssertTrue(draft.waitForExistence(timeout: 5))
        capture(app, "Conversation")
        draft.tap(); draft.typeText("Let’s work on the phone app.")
        app.buttons["Send message"].tap()
        XCTAssertTrue(app.staticTexts["You: Let’s work on the phone app."].waitForExistence(timeout: 5))
    }
    func testDotAndChatSetupAreSeparate() {
        let app = preview()
        app.tabBars.buttons["Dots"].tap()
        XCTAssertTrue(app.buttons["dot-scout"].waitForExistence(timeout: 5))
        app.buttons["dot-scout"].tap()
        XCTAssertTrue(app.buttons["setup-chat"].waitForExistence(timeout: 5))
        capture(app, "Dot setup")
        app.buttons["setup-chat"].tap()
        XCTAssertTrue(app.buttons["setup-create-chat"].waitForExistence(timeout: 5))
        app.buttons["setup-create-chat"].tap()
        XCTAssertTrue(app.buttons["setup-open-chat"].waitForExistence(timeout: 5))
        app.buttons["setup-open-chat"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["message-draft"].firstMatch.waitForExistence(timeout: 5))
    }
    func testEmptyChatsCanSetUpDotAndReachConversation() {
        let app = preview(["-demo-empty"])
        let start = app.buttons["start-setup"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        start.tap()
        let name = app.textFields["dot-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["setup-create-dot"].isEnabled)
        name.tap(); name.typeText("Willow")
        app.buttons["setup-create-dot"].tap()
        XCTAssertTrue(app.buttons["setup-create-chat"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["dot-name"].exists)
        capture(app, "Setup - Dot created")
        app.buttons["setup-create-chat"].tap()
        XCTAssertTrue(app.buttons["setup-open-chat"].waitForExistence(timeout: 5))
        capture(app, "Setup - Ready")
        app.buttons["setup-open-chat"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["message-draft"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars["Willow"].exists)
    }
    func testFinishLaterResumesTheSavedDot() {
        let app = preview()
        app.tabBars.buttons["Dots"].tap()
        app.buttons["new-dot"].tap()
        let name = app.textFields["dot-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap(); name.typeText("Willow")
        app.buttons["setup-create-dot"].tap()
        XCTAssertTrue(app.buttons["setup-create-chat"].waitForExistence(timeout: 5))
        app.buttons["Finish later"].tap()
        let saved = app.buttons.containing(.staticText, identifier: "Willow").firstMatch
        XCTAssertTrue(saved.waitForExistence(timeout: 5))
        saved.tap()
        XCTAssertTrue(app.buttons["setup-chat"].waitForExistence(timeout: 5))
        app.buttons["setup-chat"].tap()
        XCTAssertTrue(app.buttons["setup-create-chat"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["setup-create-dot"].exists)
    }
    func testEmptyChatsCanContinueExistingDotWithoutCreatingOne() {
        let app = preview(["-demo-no-chats"])
        XCTAssertTrue(app.buttons["start-setup"].waitForExistence(timeout: 5))
        app.buttons["start-setup"].tap()
        app.buttons["choose-existing-dot"].tap()
        app.buttons["continue-scout"].tap()
        XCTAssertTrue(app.buttons["setup-create-chat"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["setup-create-dot"].exists)
        app.buttons["setup-create-chat"].tap()
        app.buttons["setup-open-chat"].tap()
        XCTAssertTrue(app.navigationBars["Scout"].waitForExistence(timeout: 5))
    }
    func testSignedOutOffersDirectAndMacConnections() {
        let app = XCUIApplication()
        app.launchArguments = ["-signed-out"]
        app.launch()
        XCTAssertTrue(app.buttons["Connect ChatGPT"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Connect through your Mac"].exists)
        capture(app, "Connect")
    }

    func testMacPairingStartsWithNearbyBluetoothAndShortCode() {
        let app = XCUIApplication()
        app.launchArguments = ["-signed-out"]
        app.launch()
        app.buttons["Connect through your Mac"].tap()
        XCTAssertTrue(app.navigationBars["Connect your Mac"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.segmentedControls.buttons["Bluetooth"].isSelected)
        XCTAssertTrue(app.textFields["pairing-code"].exists)
        XCTAssertFalse(app.buttons["Pair this Mac"].isEnabled)
        capture(app, "Mac pairing")
    }

    func testContextAndCreditInformationIsAvailableBeforeSending() {
        let app = preview()
        app.buttons["dot-atlas"].tap()
        XCTAssertTrue(app.buttons["context-usage"].waitForExistence(timeout: 5))
        app.buttons["context-usage"].tap()
        XCTAssertTrue(app.navigationBars["Context & credits"].waitForExistence(timeout: 5))
        let context = app.descendants(matching: .any)["full-context-status"].firstMatch
        XCTAssertTrue(context.label.contains("not reported"))
        XCTAssertTrue(app.buttons["Save full conversation"].exists)
        app.buttons["Done"].tap()
        let draft = app.descendants(matching: .any)["message-draft"].firstMatch
        draft.tap(); draft.typeText("Implement Bluetooth")
        XCTAssertTrue(app.buttons["credit-notice"].label.contains("may use credits"))
        capture(app, "Credit notice")
    }

    func testPairingCodeDismissesKeyboardAndEnablesConfirmation() {
        let app = XCUIApplication()
        app.launchArguments = ["-signed-out"]
        app.launch()
        app.buttons["Connect through your Mac"].tap()
        app.segmentedControls.buttons["Wi-Fi"].tap()
        app.buttons["Enter an address manually"].tap()
        let address = app.textFields["http://your-mac.local:8769"]
        address.tap(); address.typeText("http://127.0.0.1:8769")
        app.buttons["Done"].tap()
        let code = app.textFields["pairing-code"]
        code.tap(); code.typeText("12345")
        XCTAssertFalse(app.buttons["pair-mac"].isEnabled)
        XCTAssertTrue(app.buttons["Done"].exists)
        code.typeText("6")
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: app.keyboards.firstMatch)
        waitForExpectations(timeout: 5)
        XCTAssertTrue(app.buttons["pair-mac"].isEnabled)
        XCTAssertTrue(app.buttons["pair-mac"].isHittable)
        capture(app, "Pairing code ready to confirm")
    }
}

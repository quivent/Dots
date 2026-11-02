package com.quivent.dots

import androidx.compose.ui.test.*
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Rule
import org.junit.Test

class DotsUiTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    private fun preview() {
        compose.onNodeWithText("Other ways to connect").performClick()
        compose.onNodeWithText("Preview with sample data").performClick()
        compose.onNodeWithText("Preview · sample data").assertExists()
    }
    @Test fun welcomeKeepsAdvancedConnectionsBehindOtherWaysAndAcceptsEightDigits() {
        compose.onNodeWithText("Join nearby").assertExists()
        compose.onNodeWithText("Connect ChatGPT directly").assertDoesNotExist()
        compose.onNodeWithText("Use an account session").assertDoesNotExist()
        compose.onNodeWithText("Enter invitation code").performClick()
        compose.onNodeWithTag("pairing-value").performTextInput("123456")
        compose.onNodeWithText("Join").assertIsNotEnabled()
        compose.onNodeWithTag("pairing-value").performTextInput("78")
        compose.onNodeWithText("Join").assertIsEnabled()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithText("Other ways to connect").performClick()
        compose.onNodeWithText("Connect through your Mac").assertExists()
        compose.onNodeWithText("Use an account session").assertExists()
    }
    @Test fun hostedSendRequiresApprovalAndCancelPreservesDraft() {
        preview()
        compose.onNodeWithTag("dot-hosted-wavesmith").performClick()
        compose.onNodeWithTag("message-draft").performTextInput("Hello")
        compose.onNodeWithContentDescription("Send message").performClick()
        compose.onNodeWithText("Approve response").assertExists()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithTag("message-draft").assertTextContains("Hello")
        compose.onNodeWithContentDescription("Send message").performClick()
        compose.onNodeWithText("Approve and send").performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("message-draft").assert(SemanticsMatcher.expectValue(androidx.compose.ui.semantics.SemanticsProperties.EditableText, androidx.compose.ui.text.AnnotatedString("")))
    }
    @Test fun researchBankOpensSynthesisAndSources() {
        preview()
        compose.onNodeWithTag("tab-Bank").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("Keeping research useful").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Keeping research useful").performClick()
        compose.onNodeWithText("Sources").assertExists()
        compose.onNodeWithText("Example source").assertExists()
        compose.onNodeWithText("Saved by Belle").assertExists()
    }
    @Test fun sharedChatIncludesSelectedMembersAndPauseIsUserControlled() {
        preview()
        compose.onNodeWithContentDescription("New chat or Dot").performClick()
        compose.onNodeWithText("New chat").performClick()
        listOf("Belle", "Oscillator", "Wavesmith").forEach { name ->
            compose.onNodeWithTag("member-hosted-" + name.lowercase()).performScrollTo().performClick()
        }
        compose.onNodeWithText("Create chat").performClick()
        compose.onNodeWithTag("message-draft").performTextInput("Discuss this")
        compose.onNodeWithContentDescription("Send message").performClick()
        compose.onNodeWithText("Listening members: Belle, Oscillator, Wavesmith").assertExists()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithText("Pause", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithText("Paused · you control Resume").assertDoesNotExist()
    }

    @Test fun oneToOneChatDoesNotApproveWorkOrWaitForAnAgent() {
        preview()
        compose.onNodeWithContentDescription("New chat or Dot").performClick()
        compose.onNodeWithText("New chat").performClick()
        compose.onNodeWithTag("person-friend").performScrollTo().performClick()
        compose.onNodeWithText("Create chat").performClick()
        compose.onNodeWithText("Just people · no agent turns").assertExists()
        compose.onNodeWithText("Pause").assertDoesNotExist()
        compose.onNodeWithTag("message-draft").performTextInput("Please deploy the app")
        compose.onNodeWithContentDescription("Send message").performClick()
        compose.onNodeWithText("Approve response").assertDoesNotExist()
        compose.onNodeWithTag("message-draft").assert(SemanticsMatcher.expectValue(androidx.compose.ui.semantics.SemanticsProperties.EditableText, androidx.compose.ui.text.AnnotatedString("")))
        val outgoing = SemanticsMatcher("Outgoing message bubble") {
            it.config.getOrNull(androidx.compose.ui.semantics.SemanticsProperties.TestTag)?.startsWith("outgoing-") == true
        }
        compose.waitUntil(10000) { compose.onAllNodes(outgoing).fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(outgoing).assertExists()
    }

    @Test fun accountSessionChoiceMatchesIPhoneAndCancelKeepsConnection() {
        preview()
        compose.onNodeWithTag("tab-Account").performClick()
        compose.onNodeWithText("Use an account session").performScrollTo().performClick()
        compose.onNodeWithText("Account session").assertExists()
        compose.onNodeWithText("ChatGPT access token").assertExists()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithText("Preview · sample data").assertExists()
    }
}

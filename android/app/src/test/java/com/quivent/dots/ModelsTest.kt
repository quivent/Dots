package com.quivent.dots

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ModelsTest {
    @Test fun otherHumanIsNotMisidentifiedAsMe() {
        val json = JSONObject("""{"id":"friend-message","role":"user","account_user_id":"phone","sender_is_self":false,"sender_display_name":"Alex","content":{"text":"Hi"}}""")
        assertFalse(Message.parse(json)!!.mine)
        assertEquals("Alex", Message.parse(json)!!.sender)
        json.put("sender_is_self", true)
        assertTrue(Message.parse(json)!!.mine)
        val room = Dot.parse(JSONObject("""{"id":"group-hub-1","human_only":true,"source":"hosted","people":[{"name":"Alex"}],"member_names":[]}"""))
        assertTrue(room.humanOnly)
        assertEquals(listOf("Alex"), room.people)
    }
    @Test fun hostedResponsesNeedApprovalButOrdinaryCloudResearchDoesNot() {
        assertTrue(needsApproval("Hello", true))
        assertTrue(needsApproval("Implement Bluetooth", false))
        assertTrue(needsApproval("Please deploy the change", false))
        assertFalse(needsApproval("Research the latest GLM results", false))
        assertFalse(needsApproval("What do you think?", false))
    }
    @Test fun contextReservesTenPercentAndHonorsSmallerWindows() {
        val page = JSONObject("""{"context_usage":{"used_tokens":899990,"max_tokens":1050000}}""")
        val budget = Budget.from(page, emptyList())
        assertEquals(1_000_000L, budget.limit)
        assertEquals(100_000L, budget.reserve)
        assertFalse(budget.blocks("Hi"))
        assertTrue(budget.blocks("x".repeat(100)))
        val smaller = Budget.from(JSONObject("""{"context_usage":{"used_tokens":90000,"max_tokens":100000}}"""), emptyList())
        assertTrue(smaller.blocks("Hi"))
        assertFalse(budget.estimated)
    }
    @Test fun lifetimeTokenTotalsDoNotBecomeReportedContext() {
        val budget = Budget.from(JSONObject("""{"total_tokens":999999}"""), listOf(Message("m", "海", true)))
        assertTrue(budget.estimated)
        assertEquals(7L, budget.used)
    }
    @Test fun actorIdentityAndHiddenReasoningAreHandled() {
        val incoming = JSONObject("""{"id":"m","role":"user","account_user_id":"calpico-member-wavesmith","sender_display_name":"Wavesmith","content":{"text":"Hello"}}""")
        assertFalse(Message.parse(incoming)!!.mine)
        assertEquals("Wavesmith", Message.parse(incoming)!!.sender)
        val raw = JSONObject().put("id", "r").put("raw_messages", JSONArray("""[
          {"author":{"role":"assistant"},"channel":"analysis","content":{"parts":["secret"]}},
          {"author":{"role":"assistant"},"channel":"final","content":{"parts":["Answer"]}}
        ]"""))
        assertEquals("Answer", Message.parse(raw)!!.text)
    }
    @Test fun endpointsLinksAndIdentifiersRejectUnsafeValues() {
        assertTrue(validEndpoint("https://dots.kosmos.institute"))
        listOf("http://dots.kosmos.institute", "https://user:pass@example.org", "https://example.org/other", "https://example.org?key=secret").forEach { assertFalse(validEndpoint(it)) }
        assertTrue(safeWebLink("https://example.org/study"))
        assertFalse(safeWebLink("file:///etc/passwd"))
        assertFalse(safeWebLink("javascript:alert(1)"))
        assertEquals("~profile", DotsApi.segment("~profile"))
        listOf("..", "a/b", "a%2Fb", "a\\b").forEach { assertThrows(IllegalArgumentException::class.java) { DotsApi.segment(it) } }
    }
    @Test fun pendingWritesRetainExactIdentityTextAndScopedApproval() {
        val pending = Pending("request-1", "hub-wavesmith", "Hello", true)
        assertEquals(pending, Pending.parse(JSONObject(pending.json().toString())))
    }

    @Test fun providerCredentialsCannotBeRoutedToHostedServer() {
        assertThrows(IllegalArgumentException::class.java) { Session("https://dots.kosmos.institute", "fixture-token", accountID = "account-1") }
        assertThrows(IllegalArgumentException::class.java) { Session("https://chatgpt.com", "fixture-token", accountID = "account-1", bluetoothAddress = "00:00:00:00:00:00") }
        val claims = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString("""{"https://api.openai.com/auth":{"chatgpt_account_id":"account-1"}}""".toByteArray())
        assertEquals("account-1", accountIDFromToken("header.$claims.signature"))
        assertNull(accountIDFromToken("sk-not-a-chatgpt-session"))
    }

    @Test fun bluetoothFramesHandlePacketSplitsAndBoundResponseSize() {
        val frames = BluetoothFrames(100)
        assertTrue(frames.append("{\"id\":".toByteArray()).isEmpty())
        assertEquals("one", frames.append("\"one\"}\n{\"id\":\"two\"}\n".toByteArray()).first().getString("id"))
        assertThrows(IllegalStateException::class.java) { BluetoothFrames(10).append("x".repeat(11).toByteArray()) }
        assertThrows(Exception::class.java) { BluetoothFrames().append("\n".toByteArray()) }
    }

    @Test fun nearbyInvitationOnlyAcceptsBoundedServerCodes() {
        val good = """{"v":1,"server":"https://dots.kosmos.institute","code":"12345678"}"""
        assertEquals("12345678", ServerInvitation.parse(good.toByteArray()).code)
        listOf(good.replace("12345678", "123456"), good.replace("12345678", "１２３４５６７８"), good.replace("dots.kosmos.institute", "example.org"), good.replace("https:", "http:"), good.replace("\"v\":1", "\"v\":2"), "x".repeat(257)).forEach {
            assertThrows(Exception::class.java) { ServerInvitation.parse(it.toByteArray()) }
        }
    }
}

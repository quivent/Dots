package com.quivent.dots

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.nio.charset.StandardCharsets
import java.io.ByteArrayOutputStream

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONObject.string(key: String): String? = optString(key).takeIf { has(key) && !isNull(key) && it.isNotEmpty() }
fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }

data class Dot(val id: String, val name: String, val summary: String = "", val room: String? = null,
               val paused: Boolean = false, val hosted: Boolean = false, val members: List<String> = emptyList(),
               val humanOnly: Boolean = false, val people: List<String> = emptyList()) {
    companion object {
        fun parse(j: JSONObject) = Dot(j.getString("id"), j.optString("display_name", "Untitled Dot"),
            j.optString("description"), j.string("messaging_room_id"), j.optBoolean("is_paused"),
            j.optString("source") == "hosted", j.optJSONArray("member_names")?.strings() ?: emptyList(),
            j.optBoolean("human_only"), j.optJSONArray("people")?.objects()?.map { it.getString("name") } ?: emptyList())
    }
}

data class Message(val id: String, val text: String, val mine: Boolean, val sender: String? = null,
                   val time: Double = 0.0, val requestID: String? = null) {
    companion object {
        fun parse(j: JSONObject): Message? {
            if (j.has("deleted_at") && !j.isNull("deleted_at")) return null
            val raw = j.optJSONArray("raw_messages")
            val text: String
            val mine: Boolean
            if (raw != null) {
                text = raw.objects().filter {
                    it.optJSONObject("author")?.optString("role") == "assistant" && it.optString("channel") != "analysis" &&
                        it.optJSONObject("metadata")?.optBoolean("is_hidden") != true && it.optJSONObject("metadata")?.optBoolean("hidden") != true
                }.map { it.optJSONObject("content")?.optJSONArray("parts")?.let { p -> (0 until p.length()).mapNotNull { n -> p.opt(n) as? String }.joinToString("\n") } ?: "" }.filter { it.isNotEmpty() }.joinToString("\n\n")
                mine = false
            } else {
                text = j.optJSONObject("content")?.optString("text") ?: return null
                val actor = j.string("account_user_id")
                mine = if (j.has("sender_is_self")) j.getBoolean("sender_is_self") else actor != null && !actor.startsWith("calpico-member") && j.optString("role") != "assistant"
            }
            if (text.isEmpty()) return null
            val time = (j.opt("created_at") as? Number)?.toDouble() ?: runCatching { java.time.Instant.parse(j.optString("created_at")).toEpochMilli() / 1000.0 }.getOrDefault(0.0)
            return Message(j.getString("id"), text, mine, if (mine) null else j.string("sender_display_name"), time,
                j.string("request_id") ?: j.string("idempotency_token"))
        }
    }
}

data class Budget(val used: Long, val limit: Long, val estimated: Boolean) {
    val reserve get() = limit / 10
    val cutoff get() = limit - reserve
    fun blocks(text: String) = used >= cutoff || estimate(text) >= cutoff - used
    companion object {
        fun estimate(text: String): Long = (text.toByteArray(StandardCharsets.UTF_8).size.toLong() + 3) / 4 + 6
        fun from(page: JSONObject?, messages: List<Message>): Budget {
            val usage = page?.optJSONObject("context_usage")
            val reported = usage?.optLong("used_tokens", -1) ?: -1
            val limit = usage?.optLong("max_tokens", 0) ?: 0
            return if (reported >= 0 && limit > 0) Budget(reported, minOf(limit, 1_000_000), false)
            else Budget(messages.sumOf { estimate(it.text) }, 1_000_000, true)
        }
    }
}

fun needsApproval(text: String, hosted: Boolean): Boolean {
    if (hosted) return true
    val draft = text.trim().lowercase()
    val prefix = "^(?:(?:please|can you|could you|would you|let's)\\s+)?"
    return Regex(prefix + "(implement|debug|refactor|compile|deploy|fix (the |a )?bug|build (an? |the )?(app|website|cli)|run (the )?(tests|code|script)|execute (the |a )?(command|script)|create (a |the )?(file|spreadsheet|document)|edit (a |the )?file|send (an? |the )?email|delete|purchase|buy|spend credits|(?:start|launch|delegate|schedule)\\b.{0,60}\\b(?:job|task|background work|research))\\b").containsMatchIn(draft)
}

data class Pending(val id: String, val room: String, val text: String, val approved: Boolean) {
    fun json() = JSONObject().put("id", id).put("room", room).put("text", text).put("approved", approved)
    companion object { fun parse(j: JSONObject) = Pending(j.getString("id"), j.getString("room"), j.getString("text"), j.optBoolean("approved")) }
}

fun safeWebLink(url: String): Boolean = runCatching {
    val uri = URI(url)
    uri.scheme?.lowercase() in listOf("https", "http", "mailto") && (uri.scheme == "mailto" || (uri.host != null && uri.userInfo == null))
}.getOrDefault(false)

fun validEndpoint(value: String): Boolean = runCatching {
    val uri = URI(value.trimEnd('/'))
    uri.scheme == "https" && uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path.isNullOrEmpty()
}.getOrDefault(false)

class BluetoothFrames(private val limit: Int = 4194304) {
    private val buffer = ByteArrayOutputStream()
    fun append(bytes: ByteArray): List<JSONObject> {
        val result = mutableListOf<JSONObject>()
        try {
            bytes.forEach { byte ->
                if (byte == 10.toByte()) {
                    check(buffer.size() + 1 <= limit) { "Bluetooth response too large" }
                    result += JSONObject(buffer.toString("UTF-8")); buffer.reset()
                } else {
                    check(buffer.size() < limit) { "Bluetooth response too large" }
                    buffer.write(byte.toInt())
                }
            }
            return result
        } catch (error: Exception) { buffer.reset(); throw error }
    }
}

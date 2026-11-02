package com.quivent.dots

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.io.IOException

data class Session(val endpoint: String, val token: String, val accountID: String? = null, val bluetoothAddress: String? = null, val hostedOnly: Boolean = false) {
    init {
        require(accountID == null || bluetoothAddress == null)
        require(token.all { it.code in 33..126 })
        require(accountID == null || accountID.isNotEmpty() && accountID.all { it.code in 33..126 })
        require(accountID == null || endpoint == "https://chatgpt.com") { "Account credentials can only be sent to ChatGPT." }
    }
    fun json() = JSONObject().put("endpoint", endpoint).put("token", token).put("account_id", accountID).put("bluetooth_address", bluetoothAddress).put("hosted_only", hostedOnly)
}
class RequestFailure(message: String, val unknown: Boolean = false, val status: Int = 0): Exception(message)

class DotsApi(private val session: Session) {
    suspend fun call(method: String = "GET", path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        require(validEndpoint(session.endpoint) && path.startsWith("/") && !path.startsWith("//"))
        val writing = method != "GET"
        session.bluetoothAddress?.let { address ->
            val uri = java.net.URI(path)
            val query = JSONObject()
            uri.rawQuery?.split('&')?.forEach { part ->
                val pair = part.split('=', limit = 2)
                query.put(java.net.URLDecoder.decode(pair[0], "UTF-8"), java.net.URLDecoder.decode(pair.getOrElse(1) { "" }, "UTF-8"))
            }
            val frame = JSONObject().put("method", method).put("path", uri.rawPath).put("query", query).put("token", session.token)
            if (body != null) frame.put("body", body)
            val response = try { BluetoothTransport.exchange(address, frame) } catch (_: Exception) { throw RequestFailure("The Mac Bluetooth connection dropped. Check history before retrying a send.", writing) }
            val status = response.getInt("status")
            if (status !in 200..299) throw RequestFailure(if (writing && status >= 500) "Delivery is uncertain. Check history before retrying." else "The Mac could not complete this request (HTTP $status).", writing && status >= 500, status)
            return@withContext response.getJSONObject("body")
        }
        val prefix = if (session.accountID != null) "/backend-api" else "/v1"
        val connection = URL(session.endpoint.trimEnd('/') + prefix + path).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15_000; connection.readTimeout = 65_000
            connection.requestMethod = method
            connection.setRequestProperty("Accept", "application/json")
            if (session.token.isNotEmpty()) connection.setRequestProperty("Authorization", "Bearer " + session.token)
            session.accountID?.let { connection.setRequestProperty("ChatGPT-Account-Id", it) }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val bytes = (if (status in 200..299) connection.inputStream else connection.errorStream)?.use { it.readBytes() }
            val result = runCatching { JSONObject(bytes?.toString(Charsets.UTF_8) ?: "{}") }.getOrNull()
            if (status !in 200..299) {
                val message = when {
                    status in 300..399 -> "The server redirected the request. Your credential was not forwarded."
                    status == 401 -> "This connection is no longer authorized. Reconnect in Account."
                    result?.optString("error_code") == "account_dot_creation_denied" -> "ChatGPT refused another account Dot. Your hosted agents and shared chats remain available."
                    result?.optString("error_code") == "work_approval_required" -> "Approve the responding Codex turns before sending."
                    status == 403 -> "The request was denied. Check pairing or the requested permission."
                    status == 429 -> "Too many requests. Wait a moment before retrying."
                    writing && (status >= 500 || status == 408) -> "The outcome is unknown. Check history before retrying."
                    else -> result?.string("error")?.take(250) ?: "Server request failed (HTTP $status)."
                }
                throw RequestFailure(message, writing && (status >= 500 || status == 408), status)
            }
            result ?: throw RequestFailure("The server returned an unexpected response.", writing)
        } catch (error: IOException) {
            if (BuildConfig.DEBUG) android.util.Log.w("DotsNetwork", "Request failed: ${error.javaClass.simpleName}")
            throw RequestFailure(if (writing) "Delivery could not be confirmed. Check history before retrying." else "Couldn’t reach the server. Pull down or tap Refresh to retry.", writing)
        } finally { connection.disconnect() }
    }

    suspend fun dots(): List<Dot> {
        val result = mutableListOf<Dot>(); val seen = mutableSetOf<String>(); var cursor: String? = null
        repeat(1000) {
            val page = call(path = "/tbo?include_room_preview=false&limit=25" + (cursor?.let { "&cursor=" + encode(it) } ?: ""))
            result += page.getJSONArray("items").objects().map(Dot::parse)
            val next = page.string("next_cursor") ?: page.string("cursor") ?: return result.distinctBy { it.id }
            if (!seen.add(next)) throw RequestFailure("The server repeated a history cursor.")
            cursor = next
        }
        throw RequestFailure("Too many result pages.")
    }

    suspend fun send(pending: Pending): String {
        val body = JSONObject().put("request_id", pending.id).put("idempotency_token", pending.id)
            .put("content", JSONObject().put("text", pending.text).put("attachments", org.json.JSONArray()))
            .put("timezone_offset_min", -java.util.TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60_000)
        if (pending.room.startsWith("hub-")) body.put("work_approved", pending.approved)
        return call("POST", "/messaging/rooms/${segment(pending.room)}/messages", body).string("id")
            ?: throw RequestFailure("Send outcome unknown. Check history.", true)
    }

    companion object {
        fun encode(value: String) = URLEncoder.encode(value, "UTF-8").replace("+", "%20")
        fun segment(value: String): String {
            require(value.isNotEmpty() && value !in listOf(".", "..") && value.none { it == '/' || it == '\\' || it == '%' || it.isISOControl() })
            return encode(value).replace("%7E", "~")
        }
    }
}

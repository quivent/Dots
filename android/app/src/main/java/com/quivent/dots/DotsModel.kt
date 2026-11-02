package com.quivent.dots

import android.app.Application
import androidx.compose.runtime.*
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class DotsModel(application: Application): AndroidViewModel(application) {
    private val vault = Vault(application)
    private var saved = JSONObject()
    var session by mutableStateOf<Session?>(null); private set
    var preview by mutableStateOf(false); private set
    var dots by mutableStateOf<List<Dot>>(emptyList()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null)
    var connectionNotice by mutableStateOf<String?>(null)
    private var hostedCatalogRevision = 0
    private var readingHostedRooms = false
    val messages = mutableStateMapOf<String, List<Message>>()
    val budgets = mutableStateMapOf<String, Budget>()
    val before = mutableStateMapOf<String, String?>()
    val pending = mutableStateMapOf<String, Pending>()
    val drafts = mutableStateMapOf<String, String>()
    val approvals = mutableStateMapOf<String, List<JSONObject>>()
    val tasks = mutableStateMapOf<String, List<JSONObject>>()
    val chatErrors = mutableStateMapOf<String, String>()
    val waiting = mutableStateMapOf<String, Boolean>()
    private val replyBaseline = mutableMapOf<String, Set<String>>()
    private var generation = UUID.randomUUID()
    val connected get() = session != null || preview
    val api get() = DotsApi(session ?: throw RequestFailure("Connect to the Dots server first."))

    init {
        BluetoothTransport.initialize(application)
        try {
            saved = vault.read()
            saved.optJSONObject("session")?.let { if (validEndpoint(it.getString("endpoint"))) session = Session(it.getString("endpoint"), it.getString("token"), it.string("account_id"), it.string("bluetooth_address"), it.optBoolean("hosted_only")) }
            saved.optJSONArray("pending")?.objects()?.map(Pending::parse)?.forEach { pending[it.room] = it }
            saved.optJSONObject("drafts")?.let { j -> j.keys().forEach { drafts[it] = j.getString(it) } }
        } catch (_: Exception) { error = "The saved connection could not be unlocked. Reconnect to continue." }
    }

    private fun persist() {
        if (preview) return
        saved.put("session", session?.json())
        saved.put("pending", JSONArray(pending.values.map { it.json() }))
        saved.put("drafts", JSONObject(drafts.toMap()))
        vault.write(saved)
    }

    fun setDraft(room: String, value: String) {
        drafts[room] = value
        runCatching { persist() }.onFailure { chatErrors[room] = "Couldn’t save this draft securely." }
    }

    fun action(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            try { block() }
            catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: Exception) { error = e.message ?: "Couldn’t complete the request." }
            finally { busy = false }
        }
    }

    suspend fun connect(endpoint: String, value: String, pairing: Boolean) {
        check(pending.isEmpty()) { "Resolve pending messages before changing connection." }
        require(validEndpoint(endpoint)) { "Use an HTTPS server address without a path." }
        val paired = if (pairing) DotsApi(Session(endpoint, "")).call("POST", "/pair", JSONObject().put("code", value).put("name", android.os.Build.MODEL.take(80))) else null
        val token = paired?.getString("token") ?: value.trim()
        val candidate = Session(endpoint.trimEnd('/'), token, hostedOnly = paired?.optString("scope") == "hosted")
        val catalog = DotsApi(candidate).dots()
        adopt(candidate, catalog)
    }

    private fun adopt(candidate: Session, catalog: List<Dot>) {
        check(pending.isEmpty()) { "Resolve pending messages before changing connection." }
        val next = JSONObject().put("session", candidate.json()).put("pending", JSONArray()).put("drafts", JSONObject())
        vault.write(next)
        saved = next; session = candidate; preview = false; dots = catalog; generation = UUID.randomUUID()
        hostedCatalogRevision++; readingHostedRooms = false; connectionNotice = null
        messages.clear(); budgets.clear(); drafts.clear(); before.clear(); approvals.clear(); tasks.clear(); chatErrors.clear(); waiting.clear()
    }

    suspend fun connectDirect(token: String, account: String) {
        val candidate = Session("https://chatgpt.com", token.trim(), account.trim())
        adopt(candidate, DotsApi(candidate).dots())
    }

    suspend fun connectBluetooth(address: String, code: String) {
        val response = BluetoothTransport.exchange(address, JSONObject().put("kind", "pair").put("code", code))
        check(response.optInt("status") == 200) { "The pairing code is invalid or expired. Generate a new code in Dots Mac." }
        val candidate = Session("https://dots.kosmos.institute", response.getJSONObject("body").getString("token"), bluetoothAddress = address)
        adopt(candidate, DotsApi(candidate).dots())
    }

    suspend fun connectHostedServer() {
        val current = session ?: return
        check(current.accountID == null) { "Pair through your Mac first. ChatGPT account credentials are never sent to the Dots server." }
        val candidate = Session("https://dots.kosmos.institute", current.token)
        adopt(candidate, DotsApi(candidate).dots())
    }

    suspend fun refresh() {
        if (preview) return
        val stamp = generation
        val revision = hostedCatalogRevision
        val catalog = api.dots()
        if (stamp == generation) {
            dots = if (session?.endpoint == "https://dots.kosmos.institute" && hostedCatalogRevision != revision) dots.filter { it.hosted } + catalog.filterNot { it.hosted } else catalog
            connectionNotice = null
        }
    }

    suspend fun refreshHostedRooms() {
        if (preview || readingHostedRooms || session?.let { it.endpoint == "https://dots.kosmos.institute" && it.accountID == null && it.bluetoothAddress == null } != true) return
        val stamp = generation
        val revision = hostedCatalogRevision
        readingHostedRooms = true
        try {
            val rooms = api.call(path = "/hosted/rooms").getJSONArray("items").objects().map(Dot::parse)
            if (stamp == generation && hostedCatalogRevision == revision) {
                dots = rooms + dots.filterNot { it.hosted }; hostedCatalogRevision++; connectionNotice = null
            }
        } finally { if (stamp == generation) readingHostedRooms = false }
    }

    fun disconnect() {
        generation = UUID.randomUUID(); session = null; preview = false; dots = emptyList()
        messages.clear(); budgets.clear(); pending.clear(); drafts.clear(); approvals.clear(); tasks.clear(); waiting.clear(); chatErrors.clear()
        saved = JSONObject(); vault.clear(); error = null
    }

    fun enterPreview() {
        preview = true; generation = UUID.randomUUID()
        dots = listOf(Dot("hosted-wavesmith", "Wavesmith", "Hosted research companion", "hub-wavesmith", hosted = true, members = listOf("Wavesmith")),
            Dot("hosted-oscillator", "Oscillator", room = "hub-oscillator", hosted = true, members = listOf("Oscillator")),
            Dot("hosted-belle", "Belle", room = "hub-belle", hosted = true, members = listOf("Belle")),
            Dot("group-preview", "Wavesmith, Oscillator & Belle", room = "hub-group", hosted = true, members = listOf("Wavesmith", "Oscillator", "Belle")),
            Dot("pocket", "Pocket", room = "cloud-room"))
        messages["hub-wavesmith"] = listOf(Message("sample-user", "Where should we keep our research?", true),
            Message("sample-dot", "We can save syntheses in the **research Bank**, with sources and uncertainty. See [the source](https://example.org/study).", false, "Wavesmith"))
    }

    suspend fun loadChat(dot: Dot, older: Boolean = false) {
        val room = dot.room ?: return
        if (preview) return
        val stamp = generation
        try {
            val page = api.call(path = "/messaging/rooms/${DotsApi.segment(room)}/messages?limit=25" + if (older) before[room]?.let { "&before=" + DotsApi.encode(it) }.orEmpty() else "")
            if (stamp != generation) return
            val incoming = page.getJSONArray("items").objects().mapNotNull(Message::parse)
            messages[room] = ((messages[room] ?: emptyList()) + incoming).associateBy { it.id }.values.sortedBy { it.time }
            if (older || !before.containsKey(room)) before[room] = page.string("prev_cursor")
            budgets[room] = Budget.from(page, messages[room] ?: emptyList())
            pending[room]?.let { p ->
                if (incoming.any { it.requestID == p.id || it.id == p.id }) { pending.remove(room); drafts[room] = ""; persist() }
            }
            if (waiting[room] == true && incoming.any { !it.mine && it.id !in replyBaseline[room].orEmpty() }) waiting[room] = false
            chatErrors.remove(room)
            if (dot.hosted && !dot.humanOnly) {
                val requests = api.call(path = "/hosted/rooms/${DotsApi.segment(room)}/approvals").getJSONArray("items").objects()
                if (stamp == generation) approvals[room] = requests
            }
            val activity = if (dot.humanOnly) emptyList() else api.call(path = "/tbo/${DotsApi.segment(dot.id)}/tasks?limit=25").optJSONArray("data")?.objects() ?: emptyList()
            if (stamp == generation) tasks[room] = activity
        } catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (e: Exception) { if (stamp == generation) chatErrors[room] = e.message ?: "Couldn’t refresh this conversation." }
    }

    fun budget(room: String) = budgets[room] ?: Budget.from(null, messages[room] ?: emptyList())

    suspend fun send(dot: Dot, text: String, approved: Boolean) {
        val room = dot.room ?: return
        check(!dot.paused) { "This Dot is paused. You control Resume." }
        check(dot.humanOnly || !budget(room).blocks(text)) { "Your 10% context reserve has been reached. Save the conversation before continuing elsewhere." }
        check(dot.humanOnly || !needsApproval(text, dot.hosted) || approved) { "Approval is required before sending." }
        check(pending[room] == null) { "Resolve the pending message first." }
        val item = Pending(UUID.randomUUID().toString(), room, text, approved)
        pending[room] = item
        try { persist() } catch (e: Exception) { pending.remove(room); throw e }
        deliver(item)
    }

    private suspend fun deliver(item: Pending) {
        val stamp = generation
        replyBaseline[item.room] = messages[item.room].orEmpty().filterNot { it.mine }.map { it.id }.toSet()
        try {
            val identity = if (preview) UUID.randomUUID().toString() else api.send(item)
            if (stamp != generation) return
            messages[item.room] = (messages[item.room] ?: emptyList()) + Message(identity, item.text, true, time = System.currentTimeMillis() / 1000.0, requestID = item.id)
            pending.remove(item.room); drafts[item.room] = ""; waiting[item.room] = dots.firstOrNull { it.room == item.room }?.humanOnly != true; persist()
        } catch (e: Exception) { chatErrors[item.room] = e.message ?: "Delivery is uncertain. Check history before retrying." }
    }

    suspend fun retry(dot: Dot) {
        val room = dot.room ?: return
        val item = pending[room] ?: return
        check(!dot.paused && (dot.humanOnly || !budget(room).blocks(item.text))) { "Paused or at the context reserve. Resolve that before retrying." }
        check(dot.humanOnly || !needsApproval(item.text, dot.hosted) || item.approved) { "This pending message needs approval." }
        deliver(item)
    }

    fun discardPending(room: String) { pending.remove(room); persist() }

    suspend fun runtime(dot: Dot) {
        val action = if (dot.paused) "resume" else "pause"
        if (preview) { dots = dots.map { if (it.id == dot.id) it.copy(paused = !it.paused) else it }; return }
        api.call("POST", "/tbo/${DotsApi.segment(dot.id)}/runtime/$action")
        val result = api.call(path = "/tbo/${DotsApi.segment(dot.id)}")
        val updated = Dot.parse(result.optJSONObject("profile") ?: result)
        dots = dots.map { if (it.id == dot.id) updated else it }
    }

    suspend fun decide(approval: JSONObject, accept: Boolean) {
        api.call("POST", "/hosted/approvals/${DotsApi.segment(approval.getString("id"))}", JSONObject().put("accept", accept))
    }

    suspend fun createRoom(name: String, members: List<String>, requestID: String, people: List<String>? = null): Dot {
        if (preview) return Dot("group-$requestID", name, room = "hub-$requestID", hosted = true, members = members.map { id -> dots.firstOrNull { it.id == id }?.name ?: id }, humanOnly = members.isEmpty(), people = if (members.isEmpty()) listOf("You", "Alex") else emptyList()).also { dots = dots + it }
        val result = api.call("POST", "/hosted/rooms", JSONObject().put("name", name).put("members", JSONArray(members)).put("request_id", requestID).also { if (people != null) it.put("people", JSONArray(people)) })
        return Dot.parse(result).also { dot -> dots = dots.filterNot { it.id == dot.id } + dot; hostedCatalogRevision++ }
    }

    suspend fun setupAccountDot(name: String): Dot {
        check(!saved.optBoolean("creation_pending")) { "An earlier creation is uncertain. Refresh Dots and open any newly created profile before trying another creation." }
        check(!preview) { "Account creation is unavailable in preview." }
        saved.put("creation_pending", true); persist()
        val result = try { api.call("POST", "/tbo", JSONObject().put("display_name", name).put("create_thread", true).put("create_additional", dots.any { !it.hosted }).put("should_initialize", true)) }
        catch (e: RequestFailure) { if (!e.unknown) { saved.remove("creation_pending"); persist() }; throw e }
        val dot = Dot.parse(result)
        check(result.string("root_thread_id") != null || result.string("active_root_thread_id") != null) { "Creation could not be confirmed. Refresh the Dot list before creating another." }
        saved.remove("creation_pending"); persist()
        dots = dots.filterNot { it.id == dot.id } + dot
        return setupRoom(dot)
    }

    suspend fun setupRoom(dot: Dot): Dot {
        if (dot.room != null) return dot
        val profile = api.call(path = "/tbo/${DotsApi.segment(dot.id)}")
        val current = Dot.parse(profile.optJSONObject("profile") ?: profile)
        if (current.room != null) {
            saved.remove("room-pending-" + dot.id); persist()
            return current.also { updated -> dots = dots.map { if (it.id == dot.id) updated else it } }
        }
        check(!saved.optBoolean("room-pending-" + dot.id)) { "Earlier chat setup is uncertain. No duplicate setup was sent. Refresh this Dot or check it in ChatGPT." }
        saved.put("room-pending-" + dot.id, true); persist()
        try {
            val response = api.call("POST", "/tbo/${DotsApi.segment(dot.id)}/messaging-room")
            val room = response.string("messaging_room_id") ?: throw RequestFailure("Chat setup outcome unknown. Refresh this Dot before retrying.", true)
            saved.remove("room-pending-" + dot.id); persist()
            return current.copy(room = room).also { updated -> dots = dots.map { if (it.id == dot.id) updated else it } }
        } catch (e: RequestFailure) {
            if (!e.unknown) { saved.remove("room-pending-" + dot.id); persist() }
            throw e
        }
    }

    suspend fun export(dot: Dot): String {
        if (preview) return transcript(messages[dot.room] ?: emptyList())
        val collected = linkedMapOf<String, Message>(); val seen = mutableSetOf<String>(); var cursor: String? = null
        repeat(1000) {
            val page = api.call(path = "/messaging/rooms/${DotsApi.segment(dot.room!!)}/messages?limit=25" + (cursor?.let { "&before=" + DotsApi.encode(it) } ?: ""))
            page.getJSONArray("items").objects().mapNotNull(Message::parse).forEach { collected[it.id] = it }
            val next = page.string("prev_cursor") ?: return transcript(collected.values.sortedBy { it.time })
            check(seen.add(next)) { "The provider repeated a history cursor." }; cursor = next
        }
        error("Too many history pages.")
    }

    private fun transcript(items: List<Message>) = items.joinToString("\n\n") { (if (it.mine) "You" else it.sender ?: "Dot") + ": " + it.text }
}

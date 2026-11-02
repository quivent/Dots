@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
package com.quivent.dots

import android.content.Intent
import android.os.Bundle
import android.text.SpannableString
import android.text.method.LinkMovementMethod
import android.text.style.URLSpan
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import io.noties.markwon.Markwon
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.text.NumberFormat
import java.util.UUID

private val Blue = Color(0xFF295CC7)
private val Purple = Color(0xFF663DA8)
private val Accent = Color(0xFF8DA2FF)
private fun count(n: Long) = NumberFormat.getIntegerInstance().format(n)
fun share(context: android.content.Context, title: String, text: String) {
    context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_SUBJECT, title).putExtra(Intent.EXTRA_TEXT, text), "Share $title"))
}

class MainActivity: ComponentActivity() {
    private val model: DotsModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Accent, background = Color(0xFF101114), surface = Color(0xFF101114), surfaceVariant = Color(0xFF22242B))) {
                Surface(Modifier.fillMaxSize()) { DotsApp(model) }
            }
        }
    }
}

@Composable fun DotsApp(vm: DotsModel) {
    var tab by rememberSaveable { mutableStateOf("Chats") }
    var opened by rememberSaveable { mutableStateOf<String?>(null) }
    var details by rememberSaveable { mutableStateOf(false) }
    var bankEntry by rememberSaveable { mutableStateOf<String?>(null) }
    var createShared by remember { mutableStateOf(false) }
    var createAccount by remember { mutableStateOf(false) }
    var newMenu by remember { mutableStateOf(false) }
    val bankAvailable = vm.preview || vm.session?.let { it.accountID == null && it.bluetoothAddress == null && it.endpoint == "https://dots.kosmos.institute" } == true
    LaunchedEffect(bankAvailable) { if (!bankAvailable && tab == "Bank") tab = "Chats" }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm.session, vm.preview) {
        if (vm.connected) lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                try { vm.refresh() }
                catch (e: kotlinx.coroutines.CancellationException) { throw e }
                catch (e: Exception) { vm.connectionNotice = e.message ?: "Couldn’t refresh the server connection." }
                delay(30_000)
            }
        }
    }
    BackHandler(opened != null || bankEntry != null) { opened = null; bankEntry = null }
    LaunchedEffect(vm.session, vm.preview) {
        if (!vm.preview && vm.session?.let { it.endpoint == "https://dots.kosmos.institute" && it.accountID == null && it.bluetoothAddress == null } == true) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    try { vm.refreshHostedRooms() }
                    catch (e: kotlinx.coroutines.CancellationException) { throw e }
                    catch (_: Exception) { vm.connectionNotice = "Couldn’t update chats. Retrying…" }
                    delay(2_000)
                }
            }
        }
    }
    if (!vm.connected) ConnectionScreen(vm)
    else Scaffold(bottomBar = {
        if (opened == null && bankEntry == null) NavigationBar {
            (listOf("Chats" to Icons.Default.Email, "Dots" to Icons.Default.Face) +
                (if (bankAvailable) listOf("Bank" to Icons.Default.List) else emptyList()) +
                listOf("Account" to Icons.Default.AccountCircle)).forEach { (name, icon) ->
                NavigationBarItem(modifier = Modifier.testTag("tab-$name"), selected = tab == name, onClick = { tab = name }, icon = { Icon(icon, name) }, label = { Text(name) })
            }
        }
    }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (vm.preview) Text("Preview · sample data", Modifier.fillMaxWidth().background(Color(0xFF252B43)).padding(8.dp), color = Accent)
            vm.connectionNotice?.let { notice -> TextButton(onClick = { vm.action { vm.refresh() } }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text(notice + " Tap to retry.", style = MaterialTheme.typography.bodySmall) } }
            val dot = vm.dots.firstOrNull { it.id == opened }
            when {
                opened != null && dot != null -> if (details || dot.room == null) DotDetails(vm, dot, onBack = { opened = null }, onChat = { details = false }) else ChatScreen(vm, dot, onBack = { opened = null })
                bankEntry != null -> BankDetail(vm, bankEntry!!, onBack = { bankEntry = null })
                tab == "Account" -> AccountScreen(vm)
                tab == "Bank" -> BankScreen(vm) { bankEntry = it }
                else -> {
                    TopAppBar(title = { Text(tab, fontWeight = FontWeight.Bold) }, actions = {
                        IconButton(onClick = { vm.action { vm.refresh() } }, enabled = !vm.busy) { Icon(Icons.Default.Refresh, "Refresh") }
                        Box {
                            IconButton(onClick = { newMenu = true }) { Icon(Icons.Default.Add, "New chat or Dot") }
                            DropdownMenu(expanded = newMenu, onDismissRequest = { newMenu = false }) {
                                if (bankAvailable) DropdownMenuItem(text = { Text("New chat") }, onClick = { newMenu = false; createShared = true })
                                if (vm.session?.hostedOnly != true) DropdownMenuItem(text = { Text("Set up a ChatGPT Dot") }, onClick = { newMenu = false; createAccount = true })
                            }
                        }
                    })
                    var search by rememberSaveable(tab) { mutableStateOf("") }
                    OutlinedTextField(search, { search = it }, label = { Text("Search $tab") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp))
                    val visible = vm.dots.filter { (if (tab == "Chats") it.room != null else !it.humanOnly) && it.name.contains(search, ignoreCase = true) }
                    LazyColumn(Modifier.fillMaxSize()) {
                        if (visible.isEmpty()) item { Text(if (vm.busy) "Loading your Dots…" else "No Dots found. Refresh or create a shared chat.", Modifier.padding(24.dp)) }
                        items(visible, key = { it.id }) { item ->
                            ListItem(modifier = Modifier.clickable { opened = item.id; details = tab != "Chats" }.testTag("dot-${item.id}"),
                                headlineContent = { Text(item.name, fontWeight = FontWeight.SemiBold) },
                                supportingContent = { Text(if (tab == "Chats") vm.messages[item.room]?.lastOrNull()?.text ?: "Continue the conversation" else item.summary.ifBlank { if (item.paused) "Paused" else "Chat ready" }, maxLines = 2) },
                                leadingContent = { Avatar(item) }, trailingContent = { Text("›") })
                            HorizontalDivider(Modifier.padding(start = 76.dp))
                        }
                    }
                }
            }
        }
    }
    vm.error?.let { message -> AlertDialog(onDismissRequest = { vm.error = null }, title = { Text("Couldn’t complete the request") }, text = { Text(message) }, confirmButton = { TextButton(onClick = { vm.error = null }) { Text("OK") } }) }
    if (createShared) SharedChatDialog(vm, onDismiss = { createShared = false }) { dot -> opened = dot.id; details = false; createShared = false }
    if (createAccount) {
        var name by rememberSaveable { mutableStateOf("") }
        AlertDialog(onDismissRequest = { if (!vm.busy) createAccount = false }, title = { Text("Set up a ChatGPT Dot") },
            text = { Column { Text("Account access is separate from your hosted agents."); OutlinedTextField(name, { name = it.take(80) }, label = { Text("Dot name") }) } },
            dismissButton = { TextButton(onClick = { createAccount = false }, enabled = !vm.busy) { Text("Cancel") } },
            confirmButton = { TextButton(enabled = !vm.busy && name.isNotBlank(), onClick = { vm.action { val dot = vm.setupAccountDot(name.trim()); opened = dot.id; details = false; createAccount = false } }) { Text("Create Dot") } })
    }
}

@Composable private fun Avatar(dot: Dot) {
    Box(Modifier.size(46.dp).background(Blue, CircleShape), contentAlignment = Alignment.Center) {
        Text(dot.name.take(1).uppercase(), color = Color.White, style = MaterialTheme.typography.titleLarge)
        Box(Modifier.align(Alignment.BottomEnd).size(11.dp).background(if (dot.paused) Color(0xFFFFA545) else Color(0xFF42CF79), CircleShape))
    }
}

@Composable private fun ConnectionScreen(vm: DotsModel) {
    var endpoint by rememberSaveable { mutableStateOf("https://dots.kosmos.institute") }
    var value by rememberSaveable { mutableStateOf("") }
    var useCode by rememberSaveable { mutableStateOf(true) }
    var advanced by rememberSaveable { mutableStateOf(false) }
    var other by remember { mutableStateOf(false) }
    var login by remember { mutableStateOf(false) }
    var manual by remember { mutableStateOf(false) }
    var bluetooth by remember { mutableStateOf(false) }
    var joinServer by rememberSaveable { mutableStateOf(false) }
    var nearbyInvitation by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(28.dp), verticalArrangement = Arrangement.Center) {
        Text("● ● ●", color = Accent, style = MaterialTheme.typography.displaySmall)
        Spacer(Modifier.height(24.dp))
        Text("Your Dots, with you.", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        Text("Join your Dots and pick up the conversation.", Modifier.padding(vertical = 16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Button(onClick = { nearbyInvitation = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Join nearby") }
        OutlinedButton(onClick = { joinServer = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) { Text("Enter invitation code") }
        TextButton(onClick = { other = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) { Text("Other ways to connect") }
    }
    if (joinServer) AlertDialog(onDismissRequest = { if (!vm.busy) joinServer = false }, title = { Text("Enter invitation code") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("On the owner's iPhone: Account → Invite a phone → Create invitation.")
            OutlinedTextField(value, { value = if (useCode) it.filter { c -> c in '0'..'9' }.take(8) else it }, label = { Text(if (useCode) "Eight-digit invitation" else "Connection token") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("pairing-value"), visualTransformation = if (useCode) androidx.compose.ui.text.input.VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = if (useCode) KeyboardType.Number else KeyboardType.Password))
            TextButton(onClick = { advanced = !advanced }, enabled = !vm.busy) { Text(if (advanced) "Hide server settings" else "Server settings") }
            if (advanced) {
                OutlinedTextField(endpoint, { endpoint = it.trim() }, label = { Text("Server address") }, singleLine = true, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                Text("A six-digit Mac pairing code also works here.", style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = { useCode = !useCode; value = "" }, enabled = !vm.busy) { Text(if (useCode) "Use a connection token" else "Use an invitation code") }
            }
        }
    }, confirmButton = {
        TextButton(enabled = !vm.busy && validEndpoint(endpoint) && (if (useCode) value.length == 8 || (advanced && value.length == 6) else value.isNotBlank()),
            onClick = { vm.action { vm.connect(endpoint, value, useCode); value = ""; joinServer = false } }) { Text(if (vm.busy) "Joining…" else "Join") }
    }, dismissButton = { TextButton(onClick = { joinServer = false }, enabled = !vm.busy) { Text("Cancel") } })
    if (other) AlertDialog(onDismissRequest = { other = false }, title = { Text("Other ways to connect") }, text = {
        Column {
            TextButton(onClick = { other = false; bluetooth = true }) { Text("Connect through your Mac") }
            TextButton(onClick = { other = false; login = true }) { Text("Connect ChatGPT directly") }
            TextButton(onClick = { other = false; manual = true }) { Text("Use an account session") }
            if (BuildConfig.DEBUG) TextButton(onClick = { other = false; vm.enterPreview() }) { Text("Preview with sample data") }
        }
    }, confirmButton = { TextButton(onClick = { other = false }) { Text("Done") } })
    if (login) ChatGPTLogin(vm) { login = false }
    if (manual) AccountSessionDialog(vm) { manual = false }
    if (bluetooth) BluetoothPairing(vm) { bluetooth = false }
    if (nearbyInvitation) NearbyInvitationDialog(vm) { nearbyInvitation = false }
}

@Composable private fun AccountScreen(vm: DotsModel) {
    var disconnect by remember { mutableStateOf(false) }
    var login by remember { mutableStateOf(false) }
    var manual by remember { mutableStateOf(false) }
    var bluetooth by remember { mutableStateOf(false) }
    var invitations by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp)) {
        Text("Account", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        Text(if (vm.session?.bluetoothAddress != null) "Mac · Bluetooth" else vm.session?.endpoint ?: "Preview", Modifier.padding(vertical = 20.dp))
        Text("Hosted agents run on the server over HTTPS. ChatGPT account Dots use your Mac connection and need it awake.")
        Text("Connection credentials, drafts and pending sends are encrypted with Android Keystore. They are excluded from backup.", Modifier.padding(vertical = 20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (!vm.preview && vm.session?.let { it.accountID == null && it.bluetoothAddress == null && !it.hostedOnly && it.endpoint == "https://dots.kosmos.institute" } == true) {
            TextButton(onClick = { invitations = true }) { Text("Invite a phone") }
        }
        TextButton(onClick = { bluetooth = true }, enabled = !vm.busy) { Text("Connect through your Mac · Bluetooth") }
        TextButton(onClick = { login = true }, enabled = !vm.busy) { Text("Connect ChatGPT directly") }
        TextButton(onClick = { manual = true }, enabled = !vm.busy) { Text("Use an account session") }
        if (!vm.preview && vm.session?.accountID == null && vm.session?.bluetoothAddress != null) {
            Button(onClick = { vm.action { vm.connectHostedServer() } }, enabled = !vm.busy) { Text("Connect to Dots server") }
        }
        Spacer(Modifier.height(20.dp))
        OutlinedButton(onClick = { disconnect = true }) { Text(if (vm.preview) "Exit preview" else "Disconnect this phone") }
    }
    if (login) ChatGPTLogin(vm) { login = false }
    if (manual) AccountSessionDialog(vm) { manual = false }
    if (bluetooth) BluetoothPairing(vm) { bluetooth = false }
    if (invitations) InvitationsDialog(vm) { invitations = false }
    if (disconnect) AlertDialog(onDismissRequest = { disconnect = false }, title = { Text("Disconnect?") },
        text = { Text("This clears this phone’s saved connection, drafts and pending-send records. It does not delete server chats or stop work already accepted by the server.") },
        confirmButton = { TextButton(onClick = { vm.disconnect(); disconnect = false }) { Text("Disconnect") } }, dismissButton = { TextButton(onClick = { disconnect = false }) { Text("Cancel") } })
}

@Composable private fun DotDetails(vm: DotsModel, dot: Dot, onBack: () -> Unit, onChat: () -> Unit) {
    Column {
        TopAppBar(title = { Text(dot.name) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
            Avatar(dot); Text(dot.summary.ifBlank { "Your ongoing companion" })
            Text(if (dot.hosted) "Hosted on your server · Codex turns may use credits" else "ChatGPT account Dot")
            if (dot.members.isNotEmpty()) Text("Members: " + dot.members.joinToString())
            Text(if (dot.paused) "Paused" else "Ready")
            Button(onClick = { if (dot.room != null) onChat() else vm.action { vm.setupRoom(dot); onChat() } }, enabled = !vm.busy) { Text(if (dot.room == null) "Set up chat" else "Open chat") }
        }
    }
}

@Composable private fun SharedChatDialog(vm: DotsModel, onDismiss: () -> Unit, onCreated: (Dot) -> Unit) {
    var name by rememberSaveable { mutableStateOf("") }
    var ownName by rememberSaveable { mutableStateOf("") }
    var people by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var selectedPeople by rememberSaveable { mutableStateOf(emptyList<String>()) }
    var loading by remember { mutableStateOf(true) }
    var failure by remember { mutableStateOf<String?>(null) }
    val requestID = rememberSaveable { UUID.randomUUID().toString() }
    val agents = vm.dots.filter { it.hosted && it.id.startsWith("hosted-") }
    var selected by rememberSaveable { mutableStateOf(emptyList<String>()) }
    LaunchedEffect(Unit) {
        try {
            people = if (vm.preview) listOf(JSONObject().put("id", "owner").put("name", "You").put("is_self", true), JSONObject().put("id", "friend").put("name", "Alex").put("is_self", false)) else vm.api.call(path = "/hosted/people").getJSONArray("items").objects()
            ownName = people.firstOrNull { it.optBoolean("is_self") }?.getString("name") ?: ""
        } catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (_: Exception) { failure = "Couldn’t load people. Close this screen and try again." }
        finally { loading = false }
    }
    AlertDialog(onDismissRequest = { if (!vm.busy) onDismiss() }, title = { Text("New chat") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { OutlinedTextField(name, { name = it.take(80) }, label = { Text("Chat name (optional)") }, enabled = !vm.busy) }
            item { Text("People", style = MaterialTheme.typography.titleMedium) }
            if (loading) item { Text("Loading people…") }
            item { if (ownName.isNotEmpty()) OutlinedTextField(ownName, { ownName = it.take(80) }, label = { Text("Your display name") }, enabled = !vm.busy) }
            items(people.filterNot { it.optBoolean("is_self") }, key = { it.getString("id") }) { person ->
                val id = person.getString("id")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(modifier = Modifier.testTag("person-" + id), checked = id in selectedPeople, enabled = !vm.busy, onCheckedChange = { selectedPeople = if (it) selectedPeople + id else selectedPeople - id }); Text(person.getString("name"))
                }
            }
            if (!loading && people.none { !it.optBoolean("is_self") }) item { Text("No other people yet. Invite their phone from Account → Invite a phone.") }
            item { Text("Dots (optional)", style = MaterialTheme.typography.titleMedium) }
            items(agents, key = { it.id }) { dot -> Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(modifier = Modifier.testTag("member-" + dot.id), checked = dot.id in selected, enabled = !vm.busy, onCheckedChange = { selected = if (it) selected + dot.id else selected - dot.id }); Text(dot.name)
            } }
            item { Text(if (selected.isEmpty()) "With just people, messages go directly to the chat. No agent turns or AI credits." else "Selected Dots listen and respond when relevant. Each listening check is an approved Codex turn and may use credits. Dots reuse their saved context across chats.", style = MaterialTheme.typography.bodySmall) }
            failure?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        }
    }, confirmButton = { TextButton(enabled = !vm.busy && !loading && failure == null && ownName.isNotBlank() && (selected.isNotEmpty() || selectedPeople.isNotEmpty()), onClick = { vm.action {
        val title = name.trim().ifEmpty { (listOf(ownName.trim()) + people.filter { it.optString("id") in selectedPeople }.map { it.getString("name") } + agents.filter { it.id in selected }.map { it.name }).joinToString(" & ").take(80) }
        if (!vm.preview) vm.api.call("POST", "/hosted/people/me", JSONObject().put("name", ownName.trim()))
        onCreated(vm.createRoom(title, selected.sorted(), requestID, selectedPeople.sorted()))
    } }) { Text("Create chat") } }, dismissButton = { TextButton(onClick = onDismiss, enabled = !vm.busy) { Text("Cancel") } })
}

@Composable private fun ChatScreen(vm: DotsModel, dot: Dot, onBack: () -> Unit) {
    val room = dot.room ?: return
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val context = LocalContext.current
    var contextPanel by remember { mutableStateOf(false) }
    var approveText by rememberSaveable { mutableStateOf<String?>(null) }
    var operation by remember { mutableStateOf<JSONObject?>(null) }
    var runtime by remember { mutableStateOf(false) }
    var pendingAction by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val items = vm.messages[room] ?: emptyList()
    val nearBottom by remember { derivedStateOf { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= listState.layoutInfo.totalItemsCount - 3 } ?: true } }
    LaunchedEffect(room, vm.session, vm.preview) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { while (true) { vm.loadChat(dot); delay(if (vm.waiting[room] == true) 1000 else 2000) } }
    }
    LaunchedEffect(items.lastOrNull()?.id) { if (nearBottom && items.isNotEmpty()) listState.animateScrollToItem(items.lastIndex + if (vm.before[room] != null) 1 else 0) }
    Column(Modifier.fillMaxSize().imePadding()) {
        TopAppBar(title = { Text(dot.name, maxLines = 1, style = MaterialTheme.typography.titleMedium) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } }, actions = {
            if (!dot.humanOnly) TextButton(onClick = { runtime = true }, enabled = !vm.busy) { Text(if (dot.paused) "Resume" else "Pause") }
        })
        if (!dot.humanOnly) ContextBar(vm.budget(room)) { contextPanel = true }
        else Text(dot.people.joinToString(" · "), Modifier.padding(horizontal = 16.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (dot.paused) Text("Paused · you control Resume", Modifier.fillMaxWidth().padding(12.dp), color = Color(0xFFFFBA69))
        vm.approvals[room].orEmpty().forEach { request -> TextButton(onClick = { operation = request }) { Text(request.optString("agent") + " needs approval · Review operation", color = Color(0xFFFFBA69)) } }
        val active = vm.tasks[room].orEmpty().filter { it.optString("status") in listOf("running", "queued", "approval_needed", "in_progress", "working", "started") }
        if (active.isNotEmpty()) Text("${active.size} active response(s) · may use credits", Modifier.padding(horizontal = 16.dp, vertical = 4.dp), color = Color(0xFFFFBA69), style = MaterialTheme.typography.labelSmall)
        if (dot.hosted && dot.members.size > 1) {
            val jobs = vm.tasks[room].orEmpty()
            val latest = jobs.firstOrNull()?.optString("request_id")
            val quiet = jobs.takeWhile { it.optString("request_id") == latest }.filter { it.optString("reply_outcome") == "quiet" }
            if (quiet.isNotEmpty()) Text(quiet.joinToString { it.optString("title") } + " listened quietly", Modifier.padding(horizontal = 16.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().testTag("messages"), state = listState, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (vm.before[room] != null) item { TextButton(onClick = { vm.action { vm.loadChat(dot, true) } }) { Text("Load earlier messages") } }
            if (items.isEmpty()) item { Text("Start with what matters.\nWhat would you like to explore?", Modifier.padding(vertical = 40.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
            items(items, key = { it.id }) { message -> Bubble(message) }
            vm.pending[room]?.let { item -> item {
                Card { Column(Modifier.padding(16.dp)) {
                    Text(item.text); Text("Pending · delivery not confirmed", color = Color(0xFFFFBA69))
                    Text("No automatic retry was made.", style = MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(onClick = { vm.action { vm.loadChat(dot) } }) { Text("Check history") }
                        TextButton(onClick = { pendingAction = "retry" }, enabled = !vm.busy) { Text("Retry") }
                        TextButton(onClick = { pendingAction = "discard" }, enabled = !vm.busy) { Text("Discard") }
                    }
                } }
            } }
        }
        vm.chatErrors[room]?.let { Text(it, Modifier.padding(horizontal = 16.dp, vertical = 6.dp), color = Color(0xFFFFBA69), style = MaterialTheme.typography.bodySmall) }
        val draft = vm.drafts[room] ?: ""
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(draft, { vm.setDraft(room, it.take(12000)) }, placeholder = { Text("Message ${dot.name}") }, modifier = Modifier.weight(1f).testTag("message-draft"), maxLines = 5,
                enabled = !vm.busy && vm.pending[room] == null, shape = RoundedCornerShape(24.dp))
            IconButton(enabled = draft.isNotBlank() && !vm.busy && !dot.paused && vm.pending[room] == null && (dot.humanOnly || !vm.budget(room).blocks(draft)), onClick = {
                if (!dot.humanOnly && needsApproval(draft, dot.hosted)) approveText = draft else vm.action { vm.send(dot, draft, false) }
            }) { Icon(Icons.AutoMirrored.Filled.Send, "Send message", tint = Accent) }
        }
        Text(if (dot.humanOnly) "Just people · no agent turns" else if (dot.hosted) "Codex responses may use credits · approval required" else if (needsApproval(draft, false)) "Work request · approval required · may use credits" else "Chat and read-only lookups", Modifier.padding(start = 18.dp, bottom = 8.dp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    approveText?.let { text -> AlertDialog(onDismissRequest = { approveText = null }, title = { Text("Approve response") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (dot.hosted) Text((if (dot.members.size > 1) "Listening members: " else "Responding members: ") + dot.members.joinToString().ifBlank { dot.name })
            if (dot.members.size > 1) Text("Members speak only when relevant. Each listening check may use credits even if it stays quiet. Members do not automatically reply to each other.")
            Text("This request may start work and use credits. Approval applies to this message."); Text(text)
        } },
        dismissButton = { TextButton(onClick = { approveText = null }) { Text("Cancel") } },
        confirmButton = { TextButton(onClick = { approveText = null; vm.action { vm.send(dot, text, true) } }, enabled = !vm.busy) { Text("Approve and send") } }) }
    if (runtime) AlertDialog(onDismissRequest = { runtime = false }, title = { Text(if (dot.paused) "Resume ${dot.name}?" else "Pause ${dot.name}?") },
        text = { Text(if (dot.hosted) "This affects the member’s saved session across its rooms. Resume does not start a new response." else "The provider applies this change. Other delegated tasks may have separate controls.") },
        confirmButton = { TextButton(onClick = { runtime = false; vm.action { vm.runtime(dot) } }) { Text(if (dot.paused) "Resume" else "Pause") } }, dismissButton = { TextButton(onClick = { runtime = false }) { Text("Cancel") } })
    operation?.let { request -> AlertDialog(onDismissRequest = { if (!vm.busy) operation = null }, title = { Text(request.optString("agent") + " requests permission") },
        text = { LazyColumn { item { Text("Review this operation. Approval applies once and does not grant root access."); Text(request.optString("details")) } } },
        confirmButton = { TextButton(enabled = !vm.busy, onClick = { vm.action { vm.decide(request, true); operation = null; vm.loadChat(dot) } }) { Text("Approve once") } },
        dismissButton = { TextButton(enabled = !vm.busy, onClick = { vm.action { vm.decide(request, false); operation = null; vm.loadChat(dot) } }) { Text("Deny") } }) }
    pendingAction?.let { action -> AlertDialog(onDismissRequest = { pendingAction = null }, title = { Text(if (action == "retry") "Retry pending message?" else "Discard local pending record?") },
        text = { Text((vm.pending[room]?.text ?: "") + "\n\n" + if (action == "retry") "The same request ID and approval will be reused. Check history first; an earlier response may still arrive." else "This does not cancel work already accepted by the server. Your draft will be kept.") },
        confirmButton = { TextButton(onClick = { pendingAction = null; vm.action { if (action == "retry") vm.retry(dot) else vm.discardPending(room) } }) { Text(if (action == "retry") "Retry same request" else "Discard record") } },
        dismissButton = { TextButton(onClick = { pendingAction = null }) { Text("Cancel") } }) }
    if (contextPanel) AlertDialog(onDismissRequest = { contextPanel = false }, title = { Text("Context & credits") }, text = {
        val budget = vm.budget(room)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text((if (budget.estimated) "Loaded text estimate: ~" else "Reported usage: ") + count(budget.used) + " / " + count(budget.limit)) }
            item { Text("Send cutoff: ${count(budget.cutoff)}\nReserved buffer: ${count(budget.reserve)} (10%)") }
            item { Text("An estimate covers loaded text only. Hidden context and reply size are unknown. This guard cannot guarantee the full context stays below 1M.") }
            item { Text("Exporting or reconnecting does not reset context or grant a new allowance. Context reset is not yet available.") }
            item { Text(if (dot.hosted) "Each responding hosted member uses a Codex turn. These may consume credits, including ordinary conversation. Shared rooms reuse each member’s existing context." else "Conversation and delegated work have different provider allowances. Separate work may consume credits.") }
            item { Button(onClick = { vm.action { share(context, dot.name, vm.export(dot)) } }, enabled = !vm.busy) { Text("Save full conversation") } }
            item { Text(vm.exportVisible(room)) }
        }
    }, confirmButton = { TextButton(onClick = { contextPanel = false }) { Text("Done") } })
}

private fun DotsModel.exportVisible(room: String) = messages[room].orEmpty().joinToString("\n\n") { (if (it.mine) "You" else it.sender ?: "Dot") + ": " + it.text }

@Composable private fun ContextBar(budget: Budget, onDetails: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text((if (budget.estimated) "~" else "") + count(budget.used) + " / " + count(budget.limit), Modifier.weight(1f), style = MaterialTheme.typography.labelLarge)
            IconButton(onClick = onDetails) { Icon(Icons.Default.MoreVert, "Context details") }
        }
        Box(Modifier.fillMaxWidth().height(8.dp).background(Color(0xFF34363F), RoundedCornerShape(4.dp))) {
            Box(Modifier.fillMaxHeight().fillMaxWidth((budget.used.toFloat() / budget.limit).coerceIn(0f, 1f)).background(if (budget.used >= budget.cutoff) Color(0xFFFFBA69) else Accent, RoundedCornerShape(4.dp)))
            Box(Modifier.align(Alignment.CenterEnd).fillMaxHeight().fillMaxWidth(.1f).background(Color(0x66FFBA69)))
        }
        Text((if (budget.estimated) "Estimate · full usage unknown" else "Reported context") + " · 10% reserved", Modifier.padding(top = 5.dp, bottom = 8.dp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun Bubble(message: Message) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (message.mine) Arrangement.End else Arrangement.Start) {
        Surface(color = if (message.mine) Blue else Purple, shape = RoundedCornerShape(18.dp), modifier = Modifier.widthIn(max = 310.dp).testTag(if (message.mine) "outgoing-${message.id}" else "incoming-${message.id}")) {
            Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                message.sender?.let { Text(it, color = Color.White, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold) }
                Markdown(message.text)
            }
        }
    }
}

@Composable fun Markdown(text: String) {
    val context = LocalContext.current
    val markwon = remember(context) { Markwon.builder(context).usePlugin(object : io.noties.markwon.AbstractMarkwonPlugin() {
        override fun configureConfiguration(builder: io.noties.markwon.MarkwonConfiguration.Builder) {
            builder.linkResolver { view, link ->
                if (safeWebLink(link)) runCatching { view.context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(link))) }
            }
        }
    }).build() }
    AndroidView(factory = { TextView(it).apply { setTextColor(android.graphics.Color.WHITE); setLinkTextColor(android.graphics.Color.WHITE); textSize = 16f; movementMethod = LinkMovementMethod.getInstance(); setTextIsSelectable(true) } },
        update = { view ->
            val rendered = SpannableString(markwon.toMarkdown(text))
            rendered.getSpans(0, rendered.length, URLSpan::class.java).forEach { if (!safeWebLink(it.url)) rendered.removeSpan(it) }
            view.text = rendered
        })
}

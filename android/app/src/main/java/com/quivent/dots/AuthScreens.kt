@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
package com.quivent.dots

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.bluetooth.BluetoothAdapter
import android.os.Build
import android.webkit.*
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONObject
import org.json.JSONTokener
import java.net.URI
import java.util.UUID
import kotlin.coroutines.resume

@Composable fun InvitationsDialog(vm: DotsModel, onDismiss: () -> Unit) {
    val context = LocalContext.current
    var code by remember { mutableStateOf<String?>(null) }
    var phones by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var revoking by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun reload() { phones = vm.api.call(path = "/hosted/devices").getJSONArray("items").objects() }
    LaunchedEffect(Unit) { runCatching { reload() }.onFailure { vm.error = it.message } }
    AlertDialog(onDismissRequest = { if (!vm.busy) onDismiss() }, title = { Text("Invite a phone") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text("Shares your hosted Dots, chats and research Bank. This phone can approve Codex turns using the server’s allowance. Mac-backed account Dots are not included.") }
            item { Button(onClick = { vm.action { code = vm.api.call("POST", "/hosted/invitations", JSONObject()).getString("code") } }, enabled = !vm.busy) { Text("Create invitation") } }
            code?.let { value ->
                item { Text(value, style = MaterialTheme.typography.headlineMedium, fontFamily = FontFamily.Monospace) }
                item { Text("One use · valid for ten minutes. A new invitation replaces your previous unused code.") }
                item { TextButton(onClick = { share(context, "Dots invitation", "Join my Dots server: https://dots.kosmos.institute\nOn Android choose Enter invitation code; on iPhone choose Join an existing Dots server. Enter $value. Valid for ten minutes; grants hosted Dots, shared chats and Bank access.") }) { Text("Share invitation") } }
            }
            item { Text("Invited phones", style = MaterialTheme.typography.titleMedium) }
            if (phones.isEmpty()) item { Text("No invited phones yet") }
            items(phones) { phone -> Row { Text(phone.optString("name"), Modifier.weight(1f)); if (phone.optInt("revoked") != 0) Text("Revoked") else TextButton(onClick = { revoking = phone }, enabled = !vm.busy) { Text("Revoke") } } }
        }
    }, confirmButton = { TextButton(onClick = onDismiss, enabled = !vm.busy) { Text("Done") } })
    revoking?.let { phone -> AlertDialog(onDismissRequest = { revoking = null }, title = { Text("Revoke this phone?") }, text = { Text("Prevents future server requests. Work already accepted is not canceled.") },
        confirmButton = { TextButton(onClick = { vm.action { vm.api.call("POST", "/hosted/devices/" + DotsApi.segment(phone.getString("id")) + "/revoke", JSONObject()); revoking = null; reload() } }, enabled = !vm.busy) { Text("Revoke") } },
        dismissButton = { TextButton(onClick = { revoking = null }) { Text("Cancel") } }) }
}

fun accountIDFromToken(token: String): String? = runCatching {
    val parts = token.split('.')
    if (parts.size != 3) return null
    val claims = JSONObject(String(java.util.Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8))
    claims.optJSONObject("https://api.openai.com/auth")?.string("chatgpt_account_id")
}.getOrNull()

@Composable fun AccountSessionDialog(vm: DotsModel, onDismiss: () -> Unit) {
    var token by remember { mutableStateOf("") }
    var account by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = { if (!vm.busy) onDismiss() }, title = { Text("Account session") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Use a ChatGPT account session with Dot access. A Platform API key does not grant access to your Dots.")
            OutlinedTextField(token, { token = it }, label = { Text("ChatGPT access token") }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
            OutlinedTextField(account, { account = it }, label = { Text("Account ID (optional for a JWT)") }, singleLine = true)
            Text("Verified with ChatGPT before being saved in Android Keystore.", style = MaterialTheme.typography.bodySmall)
        }
    }, confirmButton = { TextButton(enabled = !vm.busy && token.isNotBlank() && (account.isNotBlank() || accountIDFromToken(token) != null), onClick = {
        vm.action { vm.connectDirect(token, account.ifBlank { accountIDFromToken(token) ?: "" }); token = ""; onDismiss() }
    }) { Text("Connect account") } }, dismissButton = { TextButton(onClick = onDismiss, enabled = !vm.busy) { Text("Cancel") } })
}

private suspend fun WebView.script(code: String): String = suspendCancellableCoroutine { waiter ->
    evaluateJavascript(code) { if (waiter.isActive) waiter.resume(it ?: "null") }
}

private suspend fun captureLogin(view: WebView): String {
    check(URI(view.url ?: "").host == "chatgpt.com" && URI(view.url ?: "").scheme == "https") { "Finish signing in to ChatGPT first." }
    val key = "__dotsLogin" + UUID.randomUUID().toString().replace("-", "")
    view.script("""(function(){ fetch('/api/auth/session',{credentials:'include'}).then(r=>{if(!r.ok)throw Error();return r.json()}).then(s=>{window['$key']={accessToken:s.accessToken}}).catch(()=>{window['$key']={error:true}});return true;})()""")
    try {
        repeat(60) {
            delay(250)
            check(URI(view.url ?: "").host == "chatgpt.com") { "Return to ChatGPT after signing in." }
            val encoded = view.script("JSON.stringify(window['$key'] || null)")
            val json = (JSONTokener(encoded).nextValue() as? String)?.let { runCatching { JSONObject(it) }.getOrNull() }
            if (json != null) return json.string("accessToken") ?: throw RequestFailure("Finish signing in, then use this account. If sign-in is blocked, connect through your Mac or use an account session.")
        }
        throw RequestFailure("Sign-in check timed out. Finish signing in, then try again.")
    } finally { view.evaluateJavascript("delete window['$key']", null) }
}

@Composable fun ChatGPTLogin(vm: DotsModel, onDismiss: () -> Unit) {
    val context = LocalContext.current
    var failure by remember { mutableStateOf<String?>(null) }
    var host by remember { mutableStateOf("chatgpt.com") }
    val browser = remember {
        CookieManager.getInstance().removeAllCookies(null)
        WebView(context).apply {
            settings.javaScriptEnabled = true; settings.domStorageEnabled = true
            settings.allowFileAccess = false; settings.allowContentAccess = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = request.url.scheme != "https"
                override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) { host = runCatching { URI(url ?: "").host }.getOrNull() ?: "" }
            }
            loadUrl("https://chatgpt.com/auth/login")
        }
    }
    DisposableEffect(browser) { onDispose { browser.stopLoading(); browser.clearCache(true); browser.destroy(); CookieManager.getInstance().removeAllCookies(null); WebStorage.getInstance().deleteAllData() } }
    Dialog(onDismissRequest = { if (!vm.busy) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) { Column(Modifier.imePadding()) {
            TopAppBar(title = { Text("Connect ChatGPT") }, navigationIcon = { IconButton(onClick = onDismiss, enabled = !vm.busy) { Icon(Icons.Default.Close, "Cancel") } })
            Text(host, Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.labelSmall)
            AndroidView(factory = { browser }, modifier = Modifier.weight(1f).fillMaxWidth())
            Column(Modifier.padding(16.dp)) {
                failure?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Text("Sign in here, then connect this account. Your session stays on this phone.", style = MaterialTheme.typography.bodySmall)
                Button(onClick = { vm.action {
                    try { val token = captureLogin(browser); val account = accountIDFromToken(token) ?: throw RequestFailure("Couldn’t determine this session’s account. Use an account session or connect through your Mac."); vm.connectDirect(token, account); onDismiss() }
                    catch (e: Exception) { failure = e.message ?: "Couldn’t connect this session." }
                } }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text(if (vm.busy) "Connecting…" else "Use this account") }
            }
        } }
    }
}

@Composable fun NearbyInvitationDialog(vm: DotsModel, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val phones by NearbyInvitation.phones.collectAsState()
    val status by NearbyInvitation.status.collectAsState()
    var selected by remember { mutableStateOf<String?>(null) }
    val permissions = if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
    fun scan() { runCatching { NearbyInvitation.scan() }.onFailure { vm.error = "Turn on Bluetooth and try again." } }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants.values.all { it }) scan() else vm.error = "Nearby devices permission is needed for Bluetooth invitations. You can also enter the eight-digit code."
    }
    fun search() {
        selected = null
        if (permissions.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }) scan()
        else launcher.launch(permissions)
    }
    LaunchedEffect(Unit) { NearbyInvitation.initialize(context); search() }
    LaunchedEffect(phones) { if (selected == null && phones.size == 1) selected = phones.first().address }
    DisposableEffect(Unit) { onDispose { NearbyInvitation.stop() } }
    AlertDialog(onDismissRequest = { if (!vm.busy) onDismiss() }, title = { Text("Join nearby") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text("On iPhone, open Account → Invite a phone → Invite nearby. Keep both apps open. Joining shares the server’s hosted Dots, chats and Bank.") }
            item { Text(status) }
            items(phones, key = { it.address }) { phone -> Row { RadioButton(selected = selected == phone.address, onClick = { selected = phone.address }, enabled = !vm.busy); TextButton(onClick = { selected = phone.address }, enabled = !vm.busy) { Text(phone.name) } } }
            item { TextButton(onClick = { search() }, enabled = !vm.busy) { Text("Search again") } }
            if (status.contains("Turn on")) item { TextButton(onClick = { runCatching { context.startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)) } }) { Text("Turn on Bluetooth") } }
        }
    }, confirmButton = {
        TextButton(enabled = !vm.busy && selected != null, onClick = { vm.action {
            val invitation = NearbyInvitation.receive(selected!!)
            vm.connect(invitation.server, invitation.code, true)
            onDismiss()
        } }) { Text(if (vm.busy) "Waiting for iPhone…" else "Join") }
    }, dismissButton = { TextButton(onClick = { NearbyInvitation.stop(); onDismiss() }, enabled = !vm.busy) { Text("Cancel") } })
}

@Composable fun BluetoothPairing(vm: DotsModel, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val nearby by BluetoothTransport.nearby.collectAsState()
    val status by BluetoothTransport.status.collectAsState()
    var selected by remember { mutableStateOf<String?>(null) }
    var code by rememberSaveable { mutableStateOf("") }
    val permissions = if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants.values.all { it }) runCatching { BluetoothTransport.scan() }.onFailure { vm.error = "Turn on Bluetooth and try again." }
    }
    fun search() {
        if (permissions.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }) runCatching { BluetoothTransport.scan() }.onFailure { vm.error = "Turn on Bluetooth and try again." }
        else launcher.launch(permissions)
    }
    LaunchedEffect(Unit) { search() }
    LaunchedEffect(nearby) { if (selected == null && nearby.size == 1) selected = nearby.first().address }
    DisposableEffect(Unit) { onDispose { BluetoothTransport.stopScan() } }
    Dialog(onDismissRequest = { if (!vm.busy) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) { Column(Modifier.imePadding()) {
            TopAppBar(title = { Text("Connect through your Mac") }, navigationIcon = { IconButton(onClick = onDismiss, enabled = !vm.busy) { Icon(Icons.Default.Close, "Cancel") } })
            LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                item { Text("Reuse your Mac’s ChatGPT sign-in. Open Dots Mac and choose Pair iPhone for a six-digit code; the same code works for Android.") }
                item { Text(status) }
                items(nearby, key = { it.address }) { mac -> Row { RadioButton(selected = selected == mac.address, onClick = { selected = mac.address }, enabled = !vm.busy); TextButton(onClick = { selected = mac.address }) { Text(mac.name) } } }
                item { TextButton(onClick = { search() }, enabled = !vm.busy) { Text("Search again") } }
                if (status.contains("Turn on")) item { TextButton(onClick = { runCatching { context.startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)) } }) { Text("Turn on Bluetooth") } }
                item { OutlinedTextField(code, { code = it.filter { c -> c in '0'..'9' }.take(6) }, label = { Text("Six-digit code from your Mac") }, singleLine = true, enabled = !vm.busy, keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number)) }
                item { Text("Codes work once and expire after two minutes. Your provider login stays on the Mac.", style = MaterialTheme.typography.bodySmall) }
            }
            Button(onClick = { vm.action { vm.connectBluetooth(selected!!, code); onDismiss() } }, enabled = !vm.busy && selected != null && code.length == 6, modifier = Modifier.fillMaxWidth().padding(16.dp)) { Text(if (vm.busy) "Pairing…" else "Pair this Mac") }
        } }
    }
}

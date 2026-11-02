@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
package com.quivent.dots

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date

private fun exampleResearch() = JSONObject().put("id", "preview-research").put("title", "Keeping research useful")
    .put("synthesis", "A useful synthesis keeps **evidence**, source links and uncertainty together. This is sample research for the preview.")
    .put("excerpt", "Evidence, source links and uncertainty belong together.").put("author", "Belle")
    .put("tags", JSONArray(listOf("research", "practice"))).put("created_at", System.currentTimeMillis() / 1000.0)
    .put("uncertainty", "Sample content, not a real research finding.").put("source_count", 1)
    .put("sources", JSONArray().put(JSONObject().put("title", "Example source").put("url", "https://example.org/study")))

@Composable fun BankScreen(vm: DotsModel, onEntry: (String) -> Unit) {
    var query by remember { mutableStateOf("") }
    var entries by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var before by remember { mutableStateOf<String?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load(older: Boolean = false) {
        val requested = query; val session = vm.session
        loading = true; failure = null
        try {
            val result = if (vm.preview) JSONObject().put("items", JSONArray().apply { if ("Keeping research useful".contains(query, true) || query.isBlank()) put(exampleResearch()) })
            else vm.api.call(path = "/bank/entries?q=" + DotsApi.encode(query) + (if (older) before?.let { "&before=" + DotsApi.encode(it) } else null).orEmpty())
            if (requested == query && vm.session == session) {
                val page = result.getJSONArray("items").objects()
                entries = if (older) (entries + page).distinctBy { it.getString("id") } else page
                before = result.string("next_cursor")
            }
        } catch (_: Exception) { if (requested == query) failure = "Couldn’t load the Bank. Tap Refresh to retry." }
        finally { loading = false }
    }
    LaunchedEffect(query) { delay(250); load() }
    Column {
        TopAppBar(title = { Text("Bank", fontWeight = FontWeight.Bold) }, actions = { IconButton(onClick = { scope.launch { load() } }, enabled = !loading) { Icon(Icons.Default.Refresh, "Refresh research") } })
        OutlinedTextField(query, { query = it.take(300) }, label = { Text("Search research") }, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp), singleLine = true)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            failure?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
            if (loading && entries.isEmpty()) item { CircularProgressIndicator() }
            else if (entries.isEmpty()) item { Card { Column(Modifier.padding(24.dp)) {
                Text(if (query.isBlank()) "Your research bank" else "No matching research", style = MaterialTheme.typography.titleLarge)
                Text("Ask a hosted Dot to save a synthesis in the Bank. Sources, uncertainty and its author will appear here.", Modifier.padding(top = 12.dp))
            } } }
            items(entries, key = { it.getString("id") }) { entry ->
                Card(Modifier.fillMaxWidth().clickable { onEntry(entry.getString("id")) }) {
                    Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(entry.getString("title"), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(entry.optString("excerpt"), maxLines = 3)
                        Text(entry.optString("author") + " · " + DateFormat.getDateInstance().format(Date((entry.optDouble("created_at") * 1000).toLong())) + " · ${entry.optInt("source_count")} sources", style = MaterialTheme.typography.labelSmall)
                        Text(entry.optJSONArray("tags")?.strings()?.joinToString(" · ").orEmpty(), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
            if (before != null) item { TextButton(onClick = { scope.launch { load(true) } }, enabled = !loading) { Text("Load earlier research") } }
        }
    }
}

@Composable fun BankDetail(vm: DotsModel, entryID: String, onBack: () -> Unit) {
    var entry by remember(entryID) { mutableStateOf<JSONObject?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var previous by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    LaunchedEffect(entryID) { try { entry = if (vm.preview) exampleResearch() else vm.api.call(path = "/bank/entries/" + DotsApi.segment(entryID)) } catch (_: Exception) { failure = "Couldn’t load this synthesis. Return to the Bank and try again." } }
    if (previous != null) { BankDetail(vm, previous!!, onBack = { previous = null }); return }
    Column {
        TopAppBar(title = { Text("Research") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        val data = entry
        if (data == null) { Text(failure ?: "Loading synthesis…", Modifier.padding(24.dp)); return@Column }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            item { Text(data.getString("title"), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
            item { Text("Saved by " + data.optString("author"), style = MaterialTheme.typography.labelMedium) }
            item { Markdown(data.getString("synthesis")) }
            if (data.optString("uncertainty").isNotBlank()) item { Text("Uncertainty and limitations", fontWeight = FontWeight.Bold); Text(data.getString("uncertainty")) }
            item { Text("Sources", style = MaterialTheme.typography.titleMedium) }
            val sources = data.optJSONArray("sources")?.objects().orEmpty()
            if (sources.isEmpty()) item { Text("No sources supplied") }
            items(sources) { source ->
                val url = source.optString("url")
                if (safeWebLink(url)) TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }) { Text(source.optString("title")) }
            }
            data.string("supersedes")?.let { id -> item { TextButton(onClick = { previous = id }) { Text("View previous synthesis") } } }
            item { OutlinedButton(onClick = {
                val text = data.getString("title") + "\n\n" + data.getString("synthesis") + "\n\nUncertainty: " + data.optString("uncertainty") + "\n\nSources:\n" + sources.joinToString("\n") { it.optString("title") + "\n" + it.optString("url") } + "\n\nSaved by " + data.optString("author") + " · Bank entry " + data.getString("id")
                share(context, data.getString("title"), text)
            }) { Text("Share synthesis") } }
        }
    }
}

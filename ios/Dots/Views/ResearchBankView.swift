import SwiftUI

struct ResearchEntry: Identifiable {
    let id: String
    let title: String
    let text: String
    let author: String
    let tags: [String]
    let sources: [ResearchSource]
    let sourceCount: Int
    let uncertainty: String
    let supersedes: String?
    let date: Date

    init(json: [String: Any]) throws {
        guard let id = json["id"] as? String, let title = json["title"] as? String else { throw APIError.invalidResponse }
        self.id = id; self.title = title
        text = json["synthesis"] as? String ?? json["excerpt"] as? String ?? ""
        author = json["author"] as? String ?? "Unknown author"
        tags = json["tags"] as? [String] ?? []
        sources = (json["sources"] as? [[String: Any]] ?? []).compactMap(ResearchSource.init)
        sourceCount = json["source_count"] as? Int ?? sources.count
        uncertainty = json["uncertainty"] as? String ?? ""
        supersedes = json["supersedes"] as? String
        date = parseDate(json["created_at"])
    }

    var shareText: String {
        title + "\n\n" + text + (uncertainty.isEmpty ? "" : "\n\nUncertainty: " + uncertainty)
            + "\n\nSources:\n" + sources.map { $0.title + "\n" + $0.url.absoluteString }.joined(separator: "\n\n")
            + "\n\nSaved by " + author + " · Bank entry " + id
    }
}

struct ResearchSource: Identifiable {
    let title: String
    let url: URL
    var id: String { url.absoluteString + title }
    init?(json: [String: Any]) {
        guard let title = json["title"] as? String, let text = json["url"] as? String,
              let url = URL(string: text), ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil, url.user == nil, url.password == nil else { return nil }
        self.title = title; self.url = url
    }
}

struct ResearchBankView: View {
    @Environment(DotsStore.self) private var store
    @State private var query = ""
    @State private var entries: [ResearchEntry] = []
    @State private var cursor: String?
    @State private var loading = false
    @State private var failure: String?

    var body: some View {
        NavigationStack {
            List {
                if let failure { InlineError(text: failure) }
                if entries.isEmpty {
                    if loading { ProgressView("Loading research…") }
                    else {
                        ContentUnavailableView(query.isEmpty ? "Your research bank" : "No matching research",
                            systemImage: "books.vertical", description: Text(query.isEmpty ? "Ask a hosted Dot to save a research synthesis in the Bank. Its sources and author will appear here." : "Try another search."))
                    }
                }
                ForEach(entries) { entry in
                    NavigationLink {
                        ResearchEntryView(entryID: entry.id)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(entry.title).font(.headline)
                            Text(entry.text).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                            Text(entry.author + " · " + entry.date.formatted(date: .abbreviated, time: .omitted) + " · \(entry.sourceCount) sources")
                                .font(.caption).foregroundStyle(.secondary)
                            if !entry.tags.isEmpty { Text(entry.tags.joined(separator: " · ")).font(.caption).foregroundStyle(Theme.outgoing) }
                        }.padding(.vertical, 5)
                    }.accessibilityIdentifier("bank-entry-" + entry.id)
                }
                if cursor != nil {
                    Button("Load earlier research") { Task { await load(older: true) } }.disabled(loading)
                }
            }
            .navigationTitle("Bank")
            .searchable(text: $query, prompt: "Search research")
            .refreshable { await load() }
            .toolbar { Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("Refresh research").disabled(loading) }
            .task(id: query) {
                do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                await load()
            }
        }
    }

    private func load(older: Bool = false) async {
        guard let account = store.account else { return }
        let requestedQuery = query
        loading = true; failure = nil
        defer { loading = false }
        do {
            var parameters = [URLQueryItem(name: "q", value: requestedQuery)]
            if older, let cursor { parameters.append(URLQueryItem(name: "before", value: cursor)) }
            let result = try await store.api.request("GET", "/bank/entries", account: account, query: parameters)
            guard !Task.isCancelled, requestedQuery == query, account.storageID == store.account?.storageID else { return }
            let page = try (result["items"] as? [[String: Any]] ?? []).map(ResearchEntry.init)
            entries = older ? entries + page.filter { next in !entries.contains { $0.id == next.id } } : page
            cursor = result["next_cursor"] as? String
        } catch {
            guard !Task.isCancelled, requestedQuery == query else { return }
            failure = "Couldn’t load the Bank. Pull down to retry."
        }
    }
}

struct ResearchEntryView: View {
    let entryID: String
    @Environment(DotsStore.self) private var store
    @State private var entry: ResearchEntry?
    @State private var failure: String?
    var body: some View {
        Group {
            if let entry {
                List {
                    Section {
                        Text(entry.title).font(.title2.weight(.semibold))
                        Text(entry.author + " · " + entry.date.formatted()).font(.caption).foregroundStyle(.secondary)
                        if !entry.tags.isEmpty { Text(entry.tags.joined(separator: " · ")).font(.caption) }
                    }
                    Section("Synthesis") { Text(MessageFormatting.attributed(entry.text)).textSelection(.enabled) }
                    if !entry.uncertainty.isEmpty { Section("Uncertainty and limitations") { Text(entry.uncertainty).textSelection(.enabled) } }
                    Section("Sources") {
                        if entry.sources.isEmpty { Text("No sources supplied").foregroundStyle(.secondary) }
                        ForEach(entry.sources) { source in
                            Link(destination: source.url) { VStack(alignment: .leading) { Text(source.title); Text(source.url.host ?? "").font(.caption).foregroundStyle(.secondary) } }
                        }
                    }
                    if let previous = entry.supersedes {
                        Section { NavigationLink("View previous synthesis") { ResearchEntryView(entryID: previous) } }
                    }
                    Section { ShareLink(item: entry.shareText) { Label("Share synthesis", systemImage: "square.and.arrow.up") } }
                }
            } else if let failure { ContentUnavailableView("Couldn’t load research", systemImage: "wifi.exclamationmark", description: Text(failure)) }
            else { ProgressView("Loading synthesis…") }
        }
        .navigationTitle("Research").navigationBarTitleDisplayMode(.inline)
        .task {
            guard let account = store.account else { return }
            do {
                let data = try await store.api.request("GET", "/bank/entries/" + DotsAPI.segment(entryID), account: account)
                entry = try ResearchEntry(json: data)
            } catch { failure = "Return to the Bank and try again." }
        }
    }
}

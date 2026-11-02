import Foundation
import Network
import Observation

/// Find Dots Mac companions on the local network.
@Observable
@MainActor
final class MacDiscovery {
    private(set) var endpoints: [NetworkMac] = []
    private(set) var isBrowsing = false
    private(set) var errorText: String?

    @ObservationIgnored private var browser: NWBrowser?
    @ObservationIgnored private var resolvers: [String: NWConnection] = [:]
    @ObservationIgnored private var resolved: [String: NetworkMac] = [:]

    func start() {
        guard browser == nil else { return }
        let params = NWParameters.tcp
        params.includePeerToPeer = true
        let browser = NWBrowser(for: .bonjour(type: "_dots._tcp", domain: nil), using: params)
        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                switch state {
                case .ready: self?.isBrowsing = true; self?.errorText = nil
                case .failed(let err): self?.isBrowsing = false; self?.errorText = err.localizedDescription
                case .cancelled: self?.isBrowsing = false
                default: break
                }
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in self?.handle(results: results) }
        }
        self.browser = browser
        browser.start(queue: .main)
    }

    func stop() {
        browser?.cancel()
        browser = nil
        resolvers.values.forEach { $0.cancel() }
        resolvers.removeAll()
        resolved.removeAll()
        endpoints = []
        isBrowsing = false
    }

    private func handle(results: Set<NWBrowser.Result>) {
        var seen = Set<String>()
        for result in results {
            guard case .service(let name, _, _, _) = result.endpoint else { continue }
            seen.insert(name)
            if resolvers[name] == nil, resolved[name] == nil {
                resolve(result, serviceName: name)
            }
        }
        for name in resolved.keys where !seen.contains(name) { resolved[name] = nil }
        for name in resolvers.keys where !seen.contains(name) {
            resolvers[name]?.cancel(); resolvers[name] = nil
        }
        publish()
    }

    private func resolve(_ result: NWBrowser.Result, serviceName: String) {
        var display = serviceName
        if case .bonjour(let txt) = result.metadata, let n = txt.dictionary["name"], !n.isEmpty {
            display = n
        }
        let conn = NWConnection(to: result.endpoint, using: .tcp)
        conn.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                guard let self else { return }
                switch state {
                case .ready:
                    if let path = conn.currentPath,
                       case .hostPort(let host, let port)? = path.remoteEndpoint {
                        self.resolved[serviceName] = NetworkMac(
                            name: display, host: Self.string(for: host), port: port.rawValue)
                    }
                    conn.cancel()
                    self.resolvers[serviceName] = nil
                    self.publish()
                case .failed, .cancelled:
                    self.resolvers[serviceName] = nil
                default: break
                }
            }
        }
        resolvers[serviceName] = conn
        conn.start(queue: .main)
    }

    private func publish() {
        endpoints = resolved.values.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    private static func string(for host: NWEndpoint.Host) -> String {
        switch host {
        case .ipv4(let a): return "\(a)"
        case .ipv6(let a):
            // Strip any %scope suffix the description may include.
            return "\(a)".split(separator: "%").first.map(String.init) ?? "\(a)"
        case .name(let n, _): return n
        @unknown default: return "\(host)"
        }
    }
}

struct NetworkMac: Identifiable {
    let name: String
    let host: String
    let port: UInt16
    var id: String { "\(host):\(port)" }
    var address: String { "http://" + (host.contains(":") ? "[" + host + "]" : host) + ":\(port)" }
}

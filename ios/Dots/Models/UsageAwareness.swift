import Foundation

struct ContextUsage: Equatable {
    static let planningTarget = 1_000_000
    let used: Int
    let limit: Int
    var fraction: Double { Double(used) / Double(limit) }
    var nearLimit: Bool { fraction >= 0.9 }

    /// Accept explicitly reported context counters, never lifetime total_tokens.
    static func reported(in response: [String: Any]) -> ContextUsage? {
        guard let context = response["context_usage"] as? [String: Any],
              let used = context["used_tokens"] as? Int, used >= 0,
              let limit = context["max_tokens"] as? Int, limit > 0 else { return nil }
        return .init(used: used, limit: limit)
    }
    static func visibleEstimate(_ messages: [ChatMessage]) -> Int {
        // A rough display estimate for loaded text only, not the model's complete context.
        messages.reduce(0) { $0 + max(1, ($1.text.utf8.count + 3) / 4) + 6 }
    }
}

/// A user planning guard, not proof of the provider's complete model input.
struct ContextBudget {
    let used: Int
    let limit: Int
    let isEstimated: Bool
    init(reported: ContextUsage?, messages: [ChatMessage]) {
        used = reported?.used ?? ContextUsage.visibleEstimate(messages)
        // Honor a smaller reported window rather than imply 1M is always available.
        limit = min(reported?.limit ?? ContextUsage.planningTarget, ContextUsage.planningTarget)
        isEstimated = reported == nil
    }
    var reserve: Int { limit / 10 }
    var sendLimit: Int { limit - reserve }
    var fraction: Double { min(1, max(0, Double(used) / Double(limit))) }
    var bufferReached: Bool { used >= sendLimit }
    func wouldEnterReserve(adding text: String) -> Bool {
        let inputEstimate = (text.utf8.count + 3) / 4 + 6
        return bufferReached || inputEstimate >= sendLimit - used
    }
}

enum WorkNotice: Equatable {
    case conversation, possibleCoding, possibleTools
    static func assess(_ draft: String) -> WorkNotice {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let request = #"^(?:(?:please|can you|could you|would you|let's)\s+)?"#
        let coding = request + #"(implement|debug|refactor|compile|deploy|fix (the |a )?bug|build (an? |the )?(app|website|cli)|run (the )?(tests|code|script)|execute (the |a )?(command|script))\b"#
        let tools = request + #"(create (a |the )?(file|spreadsheet|document)|edit (a |the )?file|send (an? |the )?email|delete|purchase|buy|spend credits|(?:start|launch|delegate|schedule)\b.{0,60}\b(?:job|task|background work|research))\b"#
        if text.range(of: coding, options: .regularExpression) != nil { return .possibleCoding }
        if text.range(of: tools, options: .regularExpression) != nil { return .possibleTools }
        return .conversation
    }
    var requiresApproval: Bool { self != .conversation }
    var label: String {
        switch self {
        case .conversation: return "Chat and lookups · no work request detected"
        case .possibleCoding: return "Code · approval required · may use credits"
        case .possibleTools: return "Work · approval required · may use credits"
        }
    }
}

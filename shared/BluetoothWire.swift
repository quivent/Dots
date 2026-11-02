import Foundation

enum BluetoothWire {
    static let service = "BCD57D01-2D94-4CFA-BD61-76DB7F267731"
    static let input = "BCD57D02-2D94-4CFA-BD61-76DB7F267731"
    static let output = "BCD57D03-2D94-4CFA-BD61-76DB7F267731"
    static let maximumRequest = 65_536
    static let maximumResponse = 4_194_304

    static func encode(_ object: [String: Any]) throws -> Data {
        var data = try JSONSerialization.data(withJSONObject: object)
        data.append(10)
        return data
    }
}

/// A newline-delimited JSON frame can span any number of negotiated BLE packets.
struct BluetoothFrames {
    private var buffer = Data()
    let limit: Int
    init(limit: Int) { self.limit = limit }
    mutating func append(_ bytes: Data) throws -> [[String: Any]] {
        buffer.append(bytes)
        var result: [[String: Any]] = []
        while let end = buffer.firstIndex(of: 10) {
            let frame = Data(buffer[..<end])
            buffer.removeSubrange(...end)
            guard frame.count + 1 <= limit else { buffer.removeAll(); throw BluetoothWireError.oversized }
            guard !frame.isEmpty, let object = try JSONSerialization.jsonObject(with: frame) as? [String: Any] else {
                buffer.removeAll(); throw BluetoothWireError.invalidFrame
            }
            result.append(object)
        }
        guard buffer.count <= limit else { buffer.removeAll(); throw BluetoothWireError.oversized }
        return result
    }
}

enum BluetoothWireError: LocalizedError {
    case oversized, invalidFrame, unavailable, disconnected, timeout
    var errorDescription: String? {
        switch self {
        case .oversized: return "This Bluetooth response is too large. Connect over Wi-Fi for this conversation."
        case .invalidFrame: return "The Bluetooth connection returned an invalid response."
        case .unavailable: return "Bluetooth is unavailable. Turn it on or connect over Wi-Fi."
        case .disconnected: return "Your Mac disconnected. Keep it nearby and awake, then reconnect."
        case .timeout: return "Your Mac didn’t respond. Keep it nearby and awake, then try again."
        }
    }
}

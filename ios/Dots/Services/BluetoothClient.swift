import CoreBluetooth
import Foundation
import Observation

struct NearbyMac: Identifiable {
    let id: UUID
    let name: String
}

@MainActor @Observable
final class BluetoothClient: NSObject, @preconcurrency CBCentralManagerDelegate, @preconcurrency CBPeripheralDelegate {
    static let shared = BluetoothClient()
    private(set) var nearby: [NearbyMac] = []
    private(set) var status = "Find your Mac over Bluetooth."
    private(set) var connectedID: UUID?
    @ObservationIgnored private var manager: CBCentralManager?
    @ObservationIgnored private var found: [UUID: CBPeripheral] = [:]
    @ObservationIgnored private var peripheral: CBPeripheral?
    @ObservationIgnored private var input: CBCharacteristic?
    @ObservationIgnored private var output: CBCharacteristic?
    @ObservationIgnored private var scanning = false
    @ObservationIgnored private var connecting: UUID?
    @ObservationIgnored private var connectWaiters: [CheckedContinuation<Void, Error>] = []
    @ObservationIgnored private var pending: [String: CheckedContinuation<[String: Any], Error>] = [:]
    @ObservationIgnored private var responses = BluetoothFrames(limit: BluetoothWire.maximumResponse)
    @ObservationIgnored private var writeQueue: [Data] = []
    @ObservationIgnored private var writing = false

    func start() {
        scanning = true
        if manager == nil {
            // A saved Mac ID is enough to reconnect on launch. Avoid adopting an
            // OS-restored subscription with stale characteristic/delegate state.
            manager = CBCentralManager(delegate: self, queue: .main)
        }
        else { scanIfReady() }
    }
    func stopScan() { scanning = false; manager?.stopScan() }

    private func scanIfReady() {
        guard scanning, manager?.state == .poweredOn else { return }
        status = "Looking for nearby Macs…"
        manager?.scanForPeripherals(withServices: [CBUUID(string: BluetoothWire.service)])
    }
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn: scanIfReady()
        case .unauthorized: status = "Allow Bluetooth for Dots in Settings."
        case .poweredOff: status = "Turn on Bluetooth to find your Mac."
        default: status = "Bluetooth is starting or unavailable."
        }
        if central.state != .poweredOn { failAll(BluetoothWireError.unavailable) }
    }
    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        found[peripheral.identifier] = peripheral
        if !nearby.contains(where: { $0.id == peripheral.identifier }) {
            nearby.append(.init(id: peripheral.identifier,
                name: advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? peripheral.name ?? "Dots Mac"))
        }
    }

    func connect(_ id: UUID) async throws {
        if connectedID == id, input != nil, output?.isNotifying == true { return }
        if manager == nil { start() }
        // Initializing Core Bluetooth is asynchronous; wait briefly for its powered-on callback.
        for _ in 0..<30 {
            if manager?.state != .unknown && manager?.state != .resetting { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        guard manager?.state == .poweredOn else { throw BluetoothWireError.unavailable }
        if connecting == id {
            return try await withCheckedThrowingContinuation { connectWaiters.append($0) }
        }
        guard connecting == nil, pending.isEmpty else { throw BluetoothWireError.disconnected }
        if let peripheral, peripheral.identifier != id { manager?.cancelPeripheralConnection(peripheral) }
        guard let device = found[id] ?? manager?.retrievePeripherals(withIdentifiers: [id]).first else { throw BluetoothWireError.disconnected }
        connecting = id; peripheral = device; input = nil; output = nil; connectedID = nil
        device.delegate = self
        try await withCheckedThrowingContinuation { continuation in
            connectWaiters.append(continuation)
            if device.state == .connected { device.discoverServices([CBUUID(string: BluetoothWire.service)]) }
            else { manager?.connect(device) }
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(25))
                guard let self, self.connecting == id else { return }
                self.manager?.cancelPeripheralConnection(device)
                self.failAll(BluetoothWireError.timeout)
            }
        }
    }
    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard peripheral.identifier == connecting else { return }
        peripheral.discoverServices([CBUUID(string: BluetoothWire.service)])
    }
    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        if self.peripheral?.identifier == peripheral.identifier { failAll(error ?? BluetoothWireError.disconnected) }
    }
    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        if self.peripheral?.identifier == peripheral.identifier { failAll(BluetoothWireError.disconnected) }
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == CBUUID(string: BluetoothWire.service) }) else {
            failAll(error ?? BluetoothWireError.unavailable); return
        }
        peripheral.discoverCharacteristics([CBUUID(string: BluetoothWire.input), CBUUID(string: BluetoothWire.output)], for: service)
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil else { failAll(error!); return }
        input = service.characteristics?.first { $0.uuid == CBUUID(string: BluetoothWire.input) }
        output = service.characteristics?.first { $0.uuid == CBUUID(string: BluetoothWire.output) }
        guard input != nil, let output else { failAll(BluetoothWireError.unavailable); return }
        // Restored connections can already be subscribed. Setting true again need not
        // produce a notification-state callback, so finish the connection immediately.
        if output.isNotifying { finishConnection(peripheral) }
        else { peripheral.setNotifyValue(true, for: output) }
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, characteristic.isNotifying else { failAll(error ?? BluetoothWireError.unavailable); return }
        finishConnection(peripheral)
    }
    private func finishConnection(_ peripheral: CBPeripheral) {
        connectedID = peripheral.identifier; connecting = nil; status = "Connected over Bluetooth"
        let waiters = connectWaiters; connectWaiters = []
        waiters.forEach { $0.resume() }
    }

    func exchange(mac: UUID, frame: [String: Any]) async throws -> [String: Any] {
        try await connect(mac)
        guard let peripheral, input != nil else { throw BluetoothWireError.disconnected }
        let id = UUID().uuidString
        var envelope = frame; envelope["id"] = id
        let data = try BluetoothWire.encode(envelope)
        guard data.count <= BluetoothWire.maximumRequest, pending.count < 4 else { throw BluetoothWireError.oversized }
        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            let size = min(512, peripheral.maximumWriteValueLength(for: .withResponse))
            guard size > 0 else { failAll(BluetoothWireError.unavailable); return }
            for offset in stride(from: 0, to: data.count, by: size) {
                writeQueue.append(Data(data[offset..<min(data.count, offset + size)]))
            }
            writeNext()
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(100))
                guard let self, let request = self.pending.removeValue(forKey: id) else { return }
                request.resume(throwing: BluetoothWireError.timeout)
            }
        }
    }
    private func writeNext() {
        guard !writing, !writeQueue.isEmpty, let peripheral, let input else { return }
        writing = true
        peripheral.writeValue(writeQueue.removeFirst(), for: input, type: .withResponse)
    }
    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil else { failAll(error!); return }
        writing = false; writeNext()
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let data = characteristic.value else { failAll(error ?? BluetoothWireError.invalidFrame); return }
        do {
            for frame in try responses.append(data) {
                guard let id = frame["id"] as? String, let waiter = pending.removeValue(forKey: id) else { continue }
                waiter.resume(returning: frame)
            }
        } catch { failAll(error) }
    }
    private func failAll(_ error: Error) {
        connectedID = nil; connecting = nil; input = nil; output = nil
        writeQueue = []; writing = false; responses = BluetoothFrames(limit: BluetoothWire.maximumResponse)
        let requests = pending; pending = [:]
        let waiters = connectWaiters; connectWaiters = []
        requests.values.forEach { $0.resume(throwing: error) }
        waiters.forEach { $0.resume(throwing: error) }
    }

    func pair(mac: UUID, code: String) async throws -> AccountSession {
        let result = try await exchange(mac: mac, frame: ["kind": "pair", "code": code])
        guard result["status"] as? Int == 200, let body = result["body"] as? [String: Any], let token = body["token"] as? String else {
            throw MacPairingError.invalidCode
        }
        return AccountSession(accessToken: token, accountID: "mac", bluetoothID: mac.uuidString,
                              macName: body["name"] as? String)
    }
}

enum MacPairingError: LocalizedError {
    case invalidCode
    var errorDescription: String? { "That pairing code is invalid or expired. On your Mac, choose Dots → Pair iPhone for a new code." }
}

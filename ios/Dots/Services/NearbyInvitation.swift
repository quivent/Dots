import CoreBluetooth
import Foundation
import Observation

// Separate from the Mac's authenticated chat transport. Only a short-lived
// server invitation crosses this service; account and device tokens never do.
@MainActor @Observable
final class NearbyInvitation: NSObject, @preconcurrency CBPeripheralManagerDelegate {
    static let serviceID = CBUUID(string: "B97C5010-92AA-4A25-AF19-61D44BDAD020")
    static let invitationID = CBUUID(string: "B97C5011-92AA-4A25-AF19-61D44BDAD020")
    private(set) var status = ""
    private(set) var active = false
    private(set) var needsApproval = false
    @ObservationIgnored private var manager: CBPeripheralManager?
    @ObservationIgnored private var payload: Data?
    @ObservationIgnored private var expires: Date?
    @ObservationIgnored private var pending: CBATTRequest?
    @ObservationIgnored private var approvedCentral: UUID?
    @ObservationIgnored private var expiryTask: Task<Void, Never>?
    @ObservationIgnored private var requestTask: Task<Void, Never>?

    func start(code: String, expires: Date) {
        stop()
        guard code.count == 8, code.allSatisfy({ "0123456789".contains($0) }), expires > Date() else {
            status = "Create a new invitation first."; return
        }
        payload = try? JSONSerialization.data(withJSONObject: ["v": 1, "server": DotsStore.hostedRelay, "code": code])
        self.expires = expires; active = true; status = "Starting Bluetooth…"
        if manager == nil { manager = CBPeripheralManager(delegate: self, queue: .main) }
        else { publish() }
        expiryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(max(0, expires.timeIntervalSinceNow)))
            guard !Task.isCancelled else { return }
            self?.stop(); self?.status = "Invitation expired. Create a new one."
        }
    }

    func stop() {
        expiryTask?.cancel(); expiryTask = nil; requestTask?.cancel(); requestTask = nil
        if let pending { manager?.respond(to: pending, withResult: .insufficientAuthorization) }
        pending = nil; needsApproval = false; active = false
        if manager?.state == .poweredOn { manager?.stopAdvertising(); manager?.removeAllServices() }
        payload = nil; expires = nil; approvedCentral = nil; status = ""
    }

    func approve() {
        guard let request = pending, let payload, let expires, expires > Date() else { stop(); return }
        approvedCentral = request.central.identifier
        pending = nil; needsApproval = false; requestTask?.cancel(); requestTask = nil
        manager?.stopAdvertising()
        request.value = payload; manager?.respond(to: request, withResult: .success)
        status = "Invitation sent. The other phone will connect to your server."
        // Allow ATT long-read continuation packets from this same central only.
        expiryTask?.cancel()
        expiryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled else { return }
            self?.stop(); self?.status = "Invitation sent."
        }
    }

    func decline() {
        if let pending { manager?.respond(to: pending, withResult: .insufficientAuthorization) }
        pending = nil; needsApproval = false; requestTask?.cancel(); requestTask = nil
        status = "Request declined. Waiting for another phone…"
    }

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        guard active else { return }
        switch peripheral.state {
        case .poweredOn: publish()
        case .unauthorized: stop(); status = "Allow Bluetooth for Dots in Settings."
        case .poweredOff: stop(); status = "Turn on Bluetooth and try Invite nearby again."
        case .unsupported: stop(); status = "Bluetooth invitations are unavailable on this device."
        default: status = "Bluetooth is starting…"
        }
    }

    private func publish() {
        guard active, manager?.state == .poweredOn else { return }
        manager?.removeAllServices()
        let service = CBMutableService(type: Self.serviceID, primary: true)
        service.characteristics = [CBMutableCharacteristic(type: Self.invitationID, properties: [.read], value: nil, permissions: [.readEncryptionRequired])]
        manager?.add(service)
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard active else { return }
        if error != nil { stop(); status = "Couldn’t start the nearby invitation. Try again."; return }
        peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [Self.serviceID], CBAdvertisementDataLocalNameKey: "Dots invitation"])
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        guard active else { return }
        if error != nil { stop(); status = "Couldn’t advertise. Try Invite nearby again." }
        else { status = "On Android, choose Join nearby. Keep this screen open." }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveRead request: CBATTRequest) {
        guard active, let payload, let expires, expires > Date(), request.characteristic.uuid == Self.invitationID else {
            peripheral.respond(to: request, withResult: .insufficientAuthorization); return
        }
        if let approvedCentral {
            guard approvedCentral == request.central.identifier else { peripheral.respond(to: request, withResult: .insufficientAuthorization); return }
            guard request.offset <= payload.count else { peripheral.respond(to: request, withResult: .invalidOffset); return }
            request.value = payload.subdata(in: request.offset..<payload.count)
            peripheral.respond(to: request, withResult: .success); return
        }
        guard pending == nil, request.offset == 0 else { peripheral.respond(to: request, withResult: .insufficientAuthorization); return }
        pending = request; needsApproval = true; status = "A nearby phone is asking to join."
        requestTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(22))
            guard !Task.isCancelled else { return }
            self?.decline(); self?.status = "Request timed out. Ask the other phone to try again."
        }
    }
}

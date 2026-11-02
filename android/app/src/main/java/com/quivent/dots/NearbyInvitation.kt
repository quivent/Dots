@file:Suppress("MissingPermission", "DEPRECATION")
package com.quivent.dots

import android.bluetooth.*
import android.bluetooth.le.*
import android.content.*
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.util.UUID

data class ServerInvitation(val server: String, val code: String) {
    companion object {
        fun parse(bytes: ByteArray): ServerInvitation {
            require(bytes.size in 1..256) { "Invalid nearby invitation." }
            val data = JSONObject(String(bytes, Charsets.UTF_8))
            require(data.getInt("v") == 1 && data.getString("server") == "https://dots.kosmos.institute") { "Unsupported nearby server invitation." }
            val code = data.getString("code")
            require(code.length == 8 && code.all { it in '0'..'9' }) { "Invalid invitation code." }
            return ServerInvitation(data.getString("server"), code)
        }
    }
}

/** Foreground, encrypted BLE invitation handoff. Subsequent traffic uses HTTPS. */
object NearbyInvitation {
    private val serviceID = UUID.fromString("B97C5010-92AA-4A25-AF19-61D44BDAD020")
    private val invitationID = UUID.fromString("B97C5011-92AA-4A25-AF19-61D44BDAD020")
    private val main = Handler(Looper.getMainLooper())
    private lateinit var context: Context
    private val adapter get() = context.getSystemService(BluetoothManager::class.java)?.adapter
    val phones = MutableStateFlow<List<NearbyMac>>(emptyList())
    val status = MutableStateFlow("")
    private var gatt: BluetoothGatt? = null
    private var result: CompletableDeferred<ServerInvitation>? = null
    private var waitingForBond = false
    private val scanTimeout = Runnable { stopScan(); if (phones.value.isEmpty()) status.value = "No invitation found. On iPhone, open Account → Invite a phone → Invite nearby." }

    fun initialize(value: Context) {
        if (::context.isInitialized) return
        context = value.applicationContext
        ContextCompat.registerReceiver(context, object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val device = intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE) ?: return
                val connection = gatt ?: return
                if (!waitingForBond || device.address != connection.device.address) return
                when (intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, 0)) {
                    BluetoothDevice.BOND_BONDED -> { waitingForBond = false; read(connection) }
                    BluetoothDevice.BOND_NONE -> fail("Bluetooth pairing was canceled. Try again or enter the invitation code.")
                }
            }
        }, IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED), ContextCompat.RECEIVER_EXPORTED)
    }

    fun scan() {
        stopScan(); phones.value = emptyList()
        if (adapter?.isEnabled != true) { status.value = "Turn on Bluetooth to find a nearby invitation."; return }
        status.value = "Looking for nearby invitations…"
        adapter?.bluetoothLeScanner?.startScan(listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(serviceID)).build()), ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanner)
        main.postDelayed(scanTimeout, 20000)
    }

    fun stopScan() {
        main.removeCallbacks(scanTimeout)
        if (::context.isInitialized) runCatching { adapter?.bluetoothLeScanner?.stopScan(scanner) }
    }

    fun stop() {
        stopScan(); result?.completeExceptionally(RequestFailure("Nearby invitation canceled."))
        val old = gatt; gatt = null; waitingForBond = false
        runCatching { old?.disconnect(); old?.close() }
    }

    private val scanner = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, scan: ScanResult) {
            main.post {
                if (phones.value.none { it.address == scan.device.address }) phones.value += NearbyMac(scan.device.address, scan.scanRecord?.deviceName ?: "Nearby Dots invitation")
            }
        }
        override fun onScanFailed(errorCode: Int) { status.value = "Bluetooth search failed. Try again or enter the invitation code." }
    }

    suspend fun receive(address: String): ServerInvitation = withContext(Dispatchers.Main.immediate) {
        check(gatt == null) { "An invitation is already being received." }
        stopScan(); result = CompletableDeferred(); status.value = "Connecting… Approve Bluetooth pairing if prompted, then Allow on iPhone."
        try {
            withTimeout(60000) {
                gatt = adapter?.getRemoteDevice(address)?.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                    ?: throw RequestFailure("Bluetooth is unavailable.")
                result!!.await()
            }
        } finally { stop(); result = null }
    }

    private fun fail(message: String) { status.value = message; result?.completeExceptionally(RequestFailure(message)) }
    private fun read(connection: BluetoothGatt) {
        val characteristic = connection.getService(serviceID)?.getCharacteristic(invitationID)
        if (characteristic == null || !connection.readCharacteristic(characteristic)) fail("Couldn’t read this invitation. Ask the owner to start Invite nearby again.")
        else status.value = "Tap Allow on the iPhone to share its invitation."
    }
    private fun received(connection: BluetoothGatt, bytes: ByteArray, code: Int) {
        if (connection !== gatt) return
        if (code == BluetoothGatt.GATT_INSUFFICIENT_AUTHENTICATION || code == BluetoothGatt.GATT_INSUFFICIENT_ENCRYPTION) {
            waitingForBond = true
            if (!connection.device.createBond() && connection.device.bondState != BluetoothDevice.BOND_BONDING) fail("Couldn’t pair. Enter the invitation code instead.")
            return
        }
        if (code != BluetoothGatt.GATT_SUCCESS) { fail("Invitation declined or expired. Ask the owner to try Invite nearby again."); return }
        try { result?.complete(ServerInvitation.parse(bytes)) }
        catch (_: Exception) { fail("The nearby phone sent an invalid invitation.") }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(connection: BluetoothGatt, code: Int, state: Int) { main.post {
            if (connection !== gatt) return@post
            if (code != BluetoothGatt.GATT_SUCCESS || state == BluetoothProfile.STATE_DISCONNECTED) fail("The nearby phone disconnected. Keep both apps open and try again.")
            else if (state == BluetoothProfile.STATE_CONNECTED && !connection.requestMtu(247)) connection.discoverServices()
        } }
        override fun onMtuChanged(connection: BluetoothGatt, mtu: Int, status: Int) { main.post { if (connection === gatt) connection.discoverServices() } }
        override fun onServicesDiscovered(connection: BluetoothGatt, code: Int) { main.post { if (connection === gatt) { if (code == BluetoothGatt.GATT_SUCCESS) read(connection) else fail("Couldn’t find the nearby invitation.") } } }
        override fun onCharacteristicRead(connection: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray, status: Int) { main.post { received(connection, value, status) } }
        override fun onCharacteristicRead(connection: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) { if (Build.VERSION.SDK_INT < 33) { val bytes = characteristic.value?.clone() ?: byteArrayOf(); main.post { received(connection, bytes, status) } } }
    }
}

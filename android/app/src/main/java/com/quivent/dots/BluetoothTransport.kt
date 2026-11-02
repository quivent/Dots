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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.UUID

data class NearbyMac(val address: String, val name: String)

/** The exact framed GATT protocol used by the iPhone and Dots Mac. */
object BluetoothTransport {
    private val serviceID = UUID.fromString("BCD57D01-2D94-4CFA-BD61-76DB7F267731")
    private val inputID = UUID.fromString("BCD57D02-2D94-4CFA-BD61-76DB7F267731")
    private val outputID = UUID.fromString("BCD57D03-2D94-4CFA-BD61-76DB7F267731")
    private val cccID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    private lateinit var context: Context
    private val main = Handler(Looper.getMainLooper())
    private val mutex = Mutex()
    val nearby = MutableStateFlow<List<NearbyMac>>(emptyList())
    val status = MutableStateFlow("Find your nearby Mac.")
    @Volatile private var gatt: BluetoothGatt? = null
    @Volatile private var ready: CompletableDeferred<Unit>? = null
    @Volatile private var response: CompletableDeferred<JSONObject>? = null
    @Volatile private var responseID: String? = null
    private var input: BluetoothGattCharacteristic? = null
    private var output: BluetoothGattCharacteristic? = null
    private var mtu = 23
    private var received = BluetoothFrames()
    private var chunks = ArrayDeque<ByteArray>()
    private val adapter get() = context.getSystemService(BluetoothManager::class.java)?.adapter

    fun initialize(value: Context) {
        if (::context.isInitialized) return
        context = value.applicationContext
        ContextCompat.registerReceiver(context, object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                val device = intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE) ?: return
                val connection = gatt ?: return
                if (device.address != connection.device.address) return
                if (intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, 0) == BluetoothDevice.BOND_BONDED && ready?.isCompleted == false) subscribe(connection)
            }
        }, IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED), ContextCompat.RECEIVER_EXPORTED)
    }

    fun scan() {
        val bluetooth = adapter
        if (bluetooth?.isEnabled != true) { status.value = "Turn on Bluetooth to find your Mac."; return }
        stopScan(); nearby.value = emptyList(); status.value = "Looking for nearby Macs…"
        bluetooth.bluetoothLeScanner.startScan(listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(serviceID)).build()),
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanner)
        main.postDelayed({ stopScan(); if (nearby.value.isEmpty()) status.value = "No Mac found. Keep Dots Mac open and Bluetooth on, then search again." }, 15000)
    }

    fun stopScan() { runCatching { adapter?.bluetoothLeScanner?.stopScan(scanner) } }
    private val scanner = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val mac = NearbyMac(result.device.address, result.scanRecord?.deviceName ?: result.device.name ?: "Dots Mac")
            if (nearby.value.none { it.address == mac.address }) nearby.value = nearby.value + mac
        }
        override fun onScanFailed(errorCode: Int) { status.value = "Bluetooth search failed ($errorCode). Try again." }
    }

    suspend fun exchange(address: String, frame: JSONObject): JSONObject = mutex.withLock {
        try {
            withTimeout(100000) {
                if (gatt?.device?.address != address || ready?.isCompleted != true || ready?.isCancelled == true) {
                    close()
                    val bluetooth = adapter ?: throw RequestFailure("Bluetooth is unavailable.")
                    check(bluetooth.isEnabled) { "Turn on Bluetooth to connect to your Mac." }
                    ready = CompletableDeferred()
                    gatt = bluetooth.getRemoteDevice(address).connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                    withTimeout(25000) { ready!!.await() }
                }
                val identity = UUID.randomUUID().toString()
                val bytes = (JSONObject(frame.toString()).put("id", identity).toString() + "\n").toByteArray(Charsets.UTF_8)
                check(bytes.size <= 65536) { "This Bluetooth request is too large. Use the server connection." }
                received = BluetoothFrames(); chunks.clear()
                responseID = identity; response = CompletableDeferred()
                val size = (mtu - 3).coerceIn(20, 512)
                bytes.asList().chunked(size).forEach { chunks.addLast(it.toByteArray()) }
                writeNext()
                response!!.await()
            }
        } catch (error: Exception) {
            close(); throw error
        } finally { response = null; responseID = null }
    }

    private fun subscribe(connection: BluetoothGatt) {
        val characteristic = output ?: return fail("The Mac has no Bluetooth output characteristic.")
        if (!connection.setCharacteristicNotification(characteristic, true)) { fail("Couldn’t enable Mac notifications."); return }
        val descriptor = characteristic.getDescriptor(cccID) ?: return fail("The Mac has no Bluetooth notification descriptor.")
        val sent = if (Build.VERSION.SDK_INT >= 33) connection.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) == BluetoothStatusCodes.SUCCESS
        else { descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE; connection.writeDescriptor(descriptor) }
        if (!sent) fail("Couldn’t subscribe to your Mac. Try reconnecting.")
    }

    private fun writeNext() {
        if (chunks.isEmpty()) return
        val connection = gatt ?: return fail("The Mac disconnected.")
        val characteristic = input ?: return fail("The Mac connection is not ready.")
        val bytes = chunks.removeFirst()
        val sent = if (Build.VERSION.SDK_INT >= 33) connection.writeCharacteristic(characteristic, bytes, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothStatusCodes.SUCCESS
        else { characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT; characteristic.value = bytes; connection.writeCharacteristic(characteristic) }
        if (!sent) fail("The Mac could not receive this request. No automatic retry was made.")
    }

    private fun accept(bytes: ByteArray) {
        try {
            for (frame in received.append(bytes)) if (frame.optString("id") == responseID) response?.complete(frame)
        } catch (_: Exception) { fail("The Mac sent an invalid or oversized response.") }
    }

    private fun fail(message: String) {
        status.value = message
        val failure = RequestFailure(message)
        ready?.completeExceptionally(failure); response?.completeExceptionally(failure)
    }
    private fun close() {
        gatt?.disconnect(); gatt?.close(); gatt = null; input = null; output = null; mtu = 23
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(connection: BluetoothGatt, result: Int, state: Int) {
            if (connection !== gatt) return
            if (result != BluetoothGatt.GATT_SUCCESS || state == BluetoothProfile.STATE_DISCONNECTED) { fail("Your Mac disconnected. Keep it nearby and awake."); close(); return }
            if (state == BluetoothProfile.STATE_CONNECTED && !connection.requestMtu(247)) connection.discoverServices()
        }
        override fun onMtuChanged(connection: BluetoothGatt, value: Int, result: Int) {
            if (connection !== gatt) return
            if (result == BluetoothGatt.GATT_SUCCESS) mtu = value
            connection.discoverServices()
        }
        override fun onServicesDiscovered(connection: BluetoothGatt, result: Int) {
            if (connection !== gatt) return
            val service = connection.getService(serviceID)
            input = service?.getCharacteristic(inputID); output = service?.getCharacteristic(outputID)
            if (result != BluetoothGatt.GATT_SUCCESS || input == null || output == null) { fail("Dots Mac service is unavailable."); return }
            subscribe(connection)
        }
        override fun onDescriptorWrite(connection: BluetoothGatt, descriptor: BluetoothGattDescriptor, result: Int) {
            if (connection !== gatt) return
            if (result == BluetoothGatt.GATT_INSUFFICIENT_AUTHENTICATION || result == BluetoothGatt.GATT_INSUFFICIENT_ENCRYPTION) {
                status.value = "Approve Bluetooth pairing on this phone and your Mac."
                connection.device.createBond(); return
            }
            if (result != BluetoothGatt.GATT_SUCCESS) { fail("Couldn’t enable Bluetooth notifications ($result)."); return }
            status.value = "Connected to your Mac"; ready?.complete(Unit)
        }
        override fun onCharacteristicWrite(connection: BluetoothGatt, characteristic: BluetoothGattCharacteristic, result: Int) {
            if (connection !== gatt) return
            if (result != BluetoothGatt.GATT_SUCCESS) fail("Bluetooth delivery failed. No automatic retry was made.") else writeNext()
        }
        override fun onCharacteristicChanged(connection: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) { if (connection === gatt) accept(value) }
        override fun onCharacteristicChanged(connection: BluetoothGatt, characteristic: BluetoothGattCharacteristic) { if (Build.VERSION.SDK_INT < 33 && connection === gatt) accept(characteristic.value) }
    }
}

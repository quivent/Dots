package com.quivent.dots

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Credentials, drafts and pending writes are encrypted; backup is disabled. */
class Vault(context: Context, name: String = "dots-private", private val alias: String = "dots-session-v1") {
    private val preferences = context.getSharedPreferences(name, Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun read(): JSONObject {
        val encrypted = preferences.getString("state", null) ?: return JSONObject()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val bytes = Base64.decode(encrypted, Base64.NO_WRAP)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return JSONObject(String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8))
    }
    fun write(state: JSONObject) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.iv + cipher.doFinal(state.toString().toByteArray(Charsets.UTF_8))
        check(preferences.edit().putString("state", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()) { "Couldn’t safely save the pending request." }
    }
    fun clear() { preferences.edit().clear().commit() }
}

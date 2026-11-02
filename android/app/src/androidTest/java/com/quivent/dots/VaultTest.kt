package com.quivent.dots

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyStore
import java.util.UUID

class VaultTest {
    @Test fun encryptedPendingStateSurvivesRecreationAndTamperingIsRejected() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val namespace = "vault-test-" + UUID.randomUUID()
        val alias = namespace + "-key"
        val vault = Vault(context, namespace, alias)
        try {
            val fixture = JSONObject().put("token", "fixture-only-token").put("pending", Pending("fixed-id", "hub-belle", "Hello", true).json())
            vault.write(fixture)
            val recreated = Vault(context, namespace, alias).read()
            assertEquals("fixture-only-token", recreated.getString("token"))
            assertEquals("fixed-id", recreated.getJSONObject("pending").getString("id"))
            val prefs = context.getSharedPreferences(namespace, 0)
            assertFalse(prefs.getString("state", "")!!.contains("fixture-only-token"))
            prefs.edit().putString("state", "not-valid-encrypted-state").commit()
            assertThrows(Exception::class.java) { Vault(context, namespace, alias).read() }
        } finally {
            vault.clear()
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        }
    }
}

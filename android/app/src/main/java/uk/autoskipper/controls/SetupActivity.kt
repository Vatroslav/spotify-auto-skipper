package uk.autoskipper.controls

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Phone-side pairing: server URL, device token, and a connection test. */
class SetupActivity : Activity() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private lateinit var settings: SettingsStore
    private lateinit var urlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        settings = SettingsStore(this)
        urlInput = findViewById(R.id.input_url)
        tokenInput = findViewById(R.id.input_token)
        status = findViewById(R.id.text_status)

        // In the title bar rather than in the layout: the body scrolls, and the one
        // moment this matters is right after a sideload, before anything is touched.
        title = getString(R.string.setup_version, BuildConfig.VERSION_NAME)

        urlInput.setText(settings.baseUrl.ifEmpty { SettingsStore.DEFAULT_URL })
        tokenInput.setText(settings.token)

        findViewById<Button>(R.id.button_save).setOnClickListener {
            save()
            status.text = getString(R.string.status_saved)
        }
        findViewById<Button>(R.id.button_test).setOnClickListener { testConnection() }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun save() {
        settings.baseUrl = urlInput.text.toString()
        settings.token = tokenInput.text.toString()
        // Reflect the normalized values back so the user sees what was stored.
        urlInput.setText(settings.baseUrl)
    }

    private fun testConnection() {
        save()
        val client = settings.apiClient()
        if (client == null) {
            status.text = getString(R.string.status_missing_token)
            return
        }
        status.text = getString(R.string.status_testing)
        scope.launch {
            val result = withContext(Dispatchers.IO) { client.getPlayback() }
            status.text = when (result) {
                is ApiResult.Ok -> describe(result.value)
                is ApiResult.Err -> result.message
            }
        }
    }

    private fun describe(snapshot: PlaybackSnapshot): String {
        val skipping = if (snapshot.skippingPaused) "skipping paused" else "skipping active"
        val track = snapshot.trackName?.let { name ->
            snapshot.artist?.let { "$name — $it" } ?: name
        } ?: "nothing playing"
        return "Connected: $skipping, $track"
    }
}

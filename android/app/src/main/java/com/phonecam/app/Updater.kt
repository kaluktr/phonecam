package com.phonecam.app

import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Auto-actualizador de PhoneCam Android.
 *
 * Usa la API de GitHub Releases para detectar nuevas versiones y descargar
 * el APK actualizado. Requiere permiso REQUEST_INSTALL_PACKAGES en el
 * AndroidManifest (Android 8+).
 *
 * Uso:
 *   val updater = Updater(context)
 *   updater.checkForUpdate { hasUpdate, version, apkUrl, notes ->
 *       if (hasUpdate) updater.downloadAndInstall(apkUrl)
 *   }
 */
class Updater(private val context: Context) {

    companion object {
        private const val TAG = "PhoneCamUpdater"
        private const val PREFS_NAME = "phonecam_updater"
        private const val KEY_LAST_CHECK = "last_check_time"
        private const val CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000L // 6 horas
    }

    interface UpdateCallback {
        fun onResult(hasUpdate: Boolean, version: String, apkUrl: String, notes: String)
    }

    /**
     * Comprueba si hay una nueva versión en GitHub.
     * Devuelve el resultado vía callback en el hilo principal.
     */
    fun checkForUpdate(callback: (Boolean, String, String, String) -> Unit) {
        Thread {
            val result = doCheck()
            Handler(Looper.getMainLooper()).post {
                callback(result.first, result.second, result.third, result.fourth)
            }
        }.start()
    }

    /**
     * Comprueba si hay actualización sin throttle (para uso manual).
     */
    fun checkForUpdateForce(callback: (Boolean, String, String, String) -> Unit) {
        Thread {
            val result = doCheck()
            Handler(Looper.getMainLooper()).post {
                callback(result.first, result.second, result.third, result.fourth)
            }
        }.start()
    }

    private fun doCheck(): Quadruple<Boolean, String, String, String> {
        try {
            val url = URL("https://api.github.com/repos/${AppConfig.GITHUB_REPO}/releases/latest")
            val conn = url.openConnection() as HttpURLConnection
            conn.setRequestProperty("User-Agent", "PhoneCam-Android")
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000

            if (conn.responseCode != 200) {
                return Quadruple(false, "", "", "")
            }

            val body = conn.inputStream.bufferedReader().readText()
            val json = JSONObject(body)

            val tagName = json.optString("tag_name", "").removePrefix("v")
            val htmlUrl = json.optString("html_url", "")
            val notes = json.optString("body", "")

            // Buscar el APK en los assets
            val assets = json.optJSONArray("assets")
            var apkUrl = ""
            if (assets != null) {
                for (i in 0 until assets.length()) {
                    val asset = assets.getJSONObject(i)
                    val name = asset.optString("name", "")
                    if (name.endsWith(".apk")) {
                        apkUrl = asset.optString("browser_download_url", "")
                        break
                    }
                }
            }

            val currentVersion = AppConfig.APP_VERSION
            val hasUpdate = compareVersions(tagName, currentVersion) > 0

            Log.i(TAG, "Check: current=$currentVersion latest=$tagName hasUpdate=$hasUpdate")
            saveLastCheckTime()

            return Quadruple(hasUpdate, tagName, apkUrl, notes)
        } catch (e: Exception) {
            Log.e(TAG, "Update check failed", e)
            return Quadruple(false, "", "", "")
        }
    }

    /**
     * Descarga el APK y lanza la instalación.
     */
    fun downloadAndInstall(apkUrl: String) {
        if (apkUrl.isEmpty()) {
            Log.w(TAG, "No APK URL provided")
            return
        }

        val request = DownloadManager.Request(Uri.parse(apkUrl))
            .setTitle("PhoneCam")
            .setDescription("Descargando actualización...")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "phonecam-update.apk")
            .setAllowedOverMetered(true)
            .setAllowedOverRoaming(true)

        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val downloadId = dm.enqueue(request)

        // Registrar receiver para cuando termine la descarga
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                val id = intent?.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1) ?: return
                if (id != downloadId) return

                // Obtener la URI del archivo descargado
                val query = DownloadManager.Query().setFilterById(downloadId)
                val cursor: Cursor? = dm.query(query)
                cursor?.use {
                    if (it.moveToFirst()) {
                        val localUriIdx = it.getColumnIndex(DownloadManager.COLUMN_LOCAL_URI)
                        val localUri = it.getString(localUriIdx)
                        if (localUri != null) {
                            installApk(Uri.parse(localUri))
                        }
                    }
                }

                context?.unregisterReceiver(this)
            }
        }

        context.registerReceiver(receiver,
            IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
            Context.RECEIVER_NOT_EXPORTED
        )

        Log.i(TAG, "Download started: $apkUrl")
    }

    private fun installApk(uri: Uri) {
        try {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            context.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Install failed", e)
        }
    }

    private fun shouldCheck(): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val lastCheck = prefs.getLong(KEY_LAST_CHECK, 0)
        return System.currentTimeMillis() - lastCheck > CHECK_INTERVAL_MS
    }

    private fun saveLastCheckTime() {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putLong(KEY_LAST_CHECK, System.currentTimeMillis()).apply()
    }

    private fun compareVersions(a: String, b: String): Int {
        val pa = a.split(".").mapNotNull { it.toIntOrNull() }
        val pb = b.split(".").mapNotNull { it.toIntOrNull() }
        for (i in 0 until maxOf(pa.size, pb.size)) {
            val va = pa.getOrElse(i) { 0 }
            val vb = pb.getOrElse(i) { 0 }
            if (va != vb) return va - vb
        }
        return 0
    }

    private data class Quadruple<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)
}

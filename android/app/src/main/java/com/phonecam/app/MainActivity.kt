package com.phonecam.app

import android.Manifest
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.text.format.Formatter
import android.util.Log
import android.util.Size
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "PhoneCam"
        private const val REQUEST_PERMISSIONS = 10
        private val REQUIRED_PERMISSIONS = arrayOf(
            Manifest.permission.CAMERA,
            Manifest.permission.INTERNET
        )
        private const val DEFAULT_PORT = 8080
    }

    private lateinit var previewView: PreviewView
    private lateinit var btnStart: Button
    private lateinit var btnSwitch: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvUrl: TextView
    private lateinit var spinnerRes: Spinner

    private var camera: Camera? = null
    private var imageCapture: ImageCapture? = null
    private var cameraProvider: ProcessCameraProvider? = null
    private var cameraFacing = CameraSelector.LENS_FACING_BACK
    private lateinit var cameraExecutor: ExecutorService

    private var mjpegServer: MjpegServer? = null
    private var serverRunning = false

    private lateinit var updater: Updater

    private val resolutions = listOf(
        "640x480" to Size(640, 480),
        "1280x720" to Size(1280, 720),
        "1920x1080" to Size(1920, 1080),
        "2560x1440" to Size(2560, 1440)
    )
    private var selectedResolution = 2 // 1080p by default

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        previewView = findViewById(R.id.previewView)
        btnStart = findViewById(R.id.btnStart)
        btnSwitch = findViewById(R.id.btnSwitch)
        tvStatus = findViewById(R.id.tvStatus)
        tvUrl = findViewById(R.id.tvUrl)
        spinnerRes = findViewById(R.id.spinnerRes)

        cameraExecutor = Executors.newSingleThreadExecutor()

        updater = Updater(this)

        spinnerRes.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            resolutions.map { it.first }
        )
        spinnerRes.setSelection(selectedResolution)
        spinnerRes.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: android.view.View?, pos: Int, id: Long) {
                selectedResolution = pos
                if (serverRunning) restartServer()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        btnStart.setOnClickListener { toggleServer() }
        btnSwitch.setOnClickListener { switchCamera() }

        if (allPermissionsGranted()) {
            startCamera()
        } else {
            ActivityCompat.requestPermissions(this, REQUIRED_PERMISSIONS, REQUEST_PERMISSIONS)
        }

        updateIpDisplay()
        checkForUpdates()
    }

    private fun allPermissionsGranted() = REQUIRED_PERMISSIONS.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_PERMISSIONS) {
            if (allPermissionsGranted()) {
                startCamera()
            } else {
                Toast.makeText(this, "Se necesitan permisos de cámara", Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            cameraProvider = cameraProviderFuture.get()
            bindCameraUseCases()
        }, ContextCompat.getMainExecutor(this))
    }

    private fun bindCameraUseCases() {
        val provider = cameraProvider ?: return

        provider.unbindAll()

        val cameraSelector = CameraSelector.Builder()
            .requireLensFacing(cameraFacing)
            .build()

        val preview = Preview.Builder()
            .build()
            .also { it.setSurfaceProvider(previewView.surfaceProvider) }

        val (w, h) = resolutions[selectedResolution].second.let { it.width to it.height }

        imageCapture = ImageCapture.Builder()
            .setTargetResolution(Size(w, h))
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .build()

        try {
            camera = provider.bindToLifecycle(this, cameraSelector, preview, imageCapture)
        } catch (e: Exception) {
            Log.e(TAG, "Camera bind failed", e)
            Toast.makeText(this, "Error al iniciar cámara", Toast.LENGTH_SHORT).show()
        }
    }

    private fun switchCamera() {
        cameraFacing = if (cameraFacing == CameraSelector.LENS_FACING_BACK)
            CameraSelector.LENS_FACING_FRONT else CameraSelector.LENS_FACING_BACK
        bindCameraUseCases()
    }

    private fun toggleServer() {
        if (serverRunning) stopServer() else startServer()
    }

    private fun startServer() {
        val capture = imageCapture ?: run {
            Toast.makeText(this, "Cámara no lista", Toast.LENGTH_SHORT).show()
            return
        }

        val (w, h) = resolutions[selectedResolution].second.let { it.width to it.height }

        mjpegServer = MjpegServer(DEFAULT_PORT, capture, w, h, cameraExecutor)
        try {
            mjpegServer?.start()
            serverRunning = true
            btnStart.text = "Detener"
            tvStatus.text = "● En vivo"
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.success))
            updateIpDisplay()
        } catch (e: Exception) {
            Log.e(TAG, "Server start failed", e)
            Toast.makeText(this, "Error al iniciar servidor", Toast.LENGTH_SHORT).show()
        }
    }

    private fun stopServer() {
        mjpegServer?.stop()
        mjpegServer = null
        serverRunning = false
        btnStart.text = "Iniciar"
        tvStatus.text = "● Detenido"
        tvStatus.setTextColor(ContextCompat.getColor(this, R.color.text_muted))
        tvUrl.text = ""
    }

    private fun restartServer() {
        if (serverRunning) {
            stopServer()
            startServer()
        }
    }

    private fun updateIpDisplay() {
        val ip = getDeviceIp()
        tvUrl.text = "http://$ip:$DEFAULT_PORT/video"
    }

    private fun getDeviceIp(): String {
        try {
            val wm = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
            val ip = wm.connectionInfo.ipAddress
            if (ip != 0) return Formatter.formatIpAddress(ip)
        } catch (_: Exception) {}

        try {
            NetworkInterface.getNetworkInterfaces()?.toList()?.forEach { intf ->
                if (intf.isLoopback || !intf.isUp) return@forEach
                intf.inetAddresses?.toList()?.forEach { addr ->
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        return addr.hostAddress ?: "0.0.0.0"
                    }
                }
            }
        } catch (_: Exception) {}

        return "0.0.0.0"
    }

    private fun checkForUpdates() {
        updater.checkForUpdate { hasUpdate, version, apkUrl, notes ->
            if (hasUpdate) {
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("Actualización disponible")
                    .setMessage("PhoneCam $version está disponible.\n\n¿Descargar e instalar?")
                    .setPositiveButton("Descargar") { _, _ ->
                        updater.downloadAndInstall(apkUrl)
                    }
                    .setNegativeButton("Ahora no", null)
                    .show()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopServer()
        cameraExecutor.shutdown()
    }
}

package com.phonecam.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.util.Log
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.Collections
import java.util.concurrent.ExecutorService
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Servidor MJPEG sencillo compatible con los endpoints de IP Webcam.
 *
 * Endpoints implementados:
 *   GET /                  → HTML con información básica
 *   GET /video             → stream MJPEG (multipart/x-mixed-replace)
 *   GET /status.json       → estado actual (resolución, FPS, cámara)
 *   GET /settings/ffc?set=on|off  → cambiar cámara (frontal/trasera)
 *   GET /settings/video_size?set=WxH  → cambiar resolución
 *   GET /settings/fps?set=N        → cambiar FPS (informativo)
 *   GET /shot.jpg          → captura JPEG única
 */
class MjpegServer(
    private val port: Int,
    private val imageCapture: ImageCapture,
    private var width: Int,
    private var height: Int,
    private val executor: ExecutorService
) {
    companion object {
        private const val TAG = "MjpegServer"
        private const val BOUNDARY = "PhoneCamFrame"
        private const val JPEG_QUALITY = 80
    }

    private var serverSocket: ServerSocket? = null
    private var running = AtomicBoolean(false)
    private var serverThread: Thread? = null
    private val clients = CopyOnWriteArrayList<Socket>()
    private var latestFrame: ByteArray? = null
    private val frameLock = Object()

    @Volatile
    var facing: String = "off" // off = trasera, on = frontal
        private set

    fun start() {
        if (running.getAndSet(true)) return
        serverSocket = ServerSocket(port)
        serverSocket?.reuseAddress = true

        // Hilo de captura de frames
        startFrameCapture()

        // Hilo del servidor HTTP
        serverThread = Thread {
            Log.i(TAG, "Server started on port $port")
            while (running.get()) {
                try {
                    val client = serverSocket?.accept() ?: break
                    clients.add(client)
                    executor.execute { handleClient(client) }
                } catch (e: IOException) {
                    if (running.get()) Log.e(TAG, "Accept error", e)
                }
            }
        }.apply {
            isDaemon = true
            name = "MjpegServer-HTTP"
            start()
        }
    }

    fun stop() {
        running.set(false)
        clients.forEach { try { it.close() } catch (_: Exception) {} }
        clients.clear()
        try { serverSocket?.close() } catch (_: Exception) {}
        serverSocket = null
        Log.i(TAG, "Server stopped")
    }

    private fun startFrameCapture() {
        Thread {
            while (running.get()) {
                captureFrame()
                try { Thread.sleep(33) } catch (_: InterruptedException) { break } // ~30 FPS
            }
        }.apply {
            isDaemon = true
            name = "MjpegServer-Capture"
            start()
        }
    }

    private fun captureFrame() {
        try {
            imageCapture.takePicture(executor, object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    try {
                        val buffer = image.planes[0].buffer
                        val bytes = ByteArray(buffer.remaining())
                        buffer.get(bytes)

                        // Rotar si es necesario
                        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        if (bitmap != null) {
                            val rotation = image.imageInfo.rotationDegrees
                            val finalBytes = if (rotation != 0) {
                                val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
                                val rotated = Bitmap.createBitmap(bitmap, 0, 0,
                                    bitmap.width, bitmap.height, matrix, true)
                                bitmap.recycle()
                                val out = ByteArrayOutputStream()
                                rotated.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
                                rotated.recycle()
                                out.toByteArray()
                            } else {
                                bytes
                            }
                            synchronized(frameLock) {
                                latestFrame = finalBytes
                            }
                            // Notificar a clientes MJPEG
                            notifyClients(finalBytes)
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Frame process error", e)
                    } finally {
                        image.close()
                    }
                }

                override fun onError(exception: ImageCaptureException) {
                    Log.e(TAG, "Capture error", exception)
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "takePicture error", e)
        }
    }

    private fun notifyClients(jpegBytes: ByteArray) {
        val header = (
            "--$BOUNDARY\r\n" +
            "Content-Type: image/jpeg\r\n" +
            "Content-Length: ${jpegBytes.size}\r\n\r\n"
        ).toByteArray()
        val footer = "\r\n".toByteArray()

        val dead = mutableListOf<Socket>()
        for (sock in clients) {
            try {
                val out = sock.getOutputStream()
                out.write(header)
                out.write(jpegBytes)
                out.write(footer)
                out.flush()
            } catch (_: Exception) {
                dead.add(sock)
            }
        }
        dead.forEach {
            clients.remove(it)
            try { it.close() } catch (_: Exception) {}
        }
    }

    private fun handleClient(sock: Socket) {
        try {
            val input = sock.getInputStream()
            val request = readRequest(input)
            if (request.isEmpty()) { sock.close(); return }

            val path = request.split(" ")[1].split("?")[0]
            val query = if ("?" in request.split(" ")[1])
                request.split(" ")[1].split("?")[1] else ""

            when (path) {
                "/" -> respondIndex(sock)
                "/video" -> respondMjpeg(sock)
                "/status.json" -> respondStatus(sock, query)
                "/settings/ffc" -> respondFfc(sock, query)
                "/settings/video_size" -> respondVideoSize(sock, query)
                "/settings/fps" -> respondFps(sock, query)
                "/shot.jpg" -> respondShot(sock)
                else -> respond404(sock)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Client handler error", e)
        } finally {
            try { sock.close() } catch (_: Exception) {}
        }
    }

    private fun readRequest(input: InputStream): String {
        val sb = StringBuilder()
        var last4 = ""
        while (true) {
            val b = input.read()
            if (b == -1) break
            sb.append(b.toChar())
            last4 = if (last4.length >= 4) last4.substring(1) + b.toChar() else last4 + b.toChar()
            if (last4.endsWith("\r\n\r\n")) break
            if (sb.length > 4096) break
        }
        return sb.toString()
    }

    // --- Responses ---

    private fun respondIndex(sock: Socket) {
        val html = """
            <!DOCTYPE html><html><head><meta charset="utf-8">
            <title>PhoneCam</title>
            <style>body{background:#0a0a0d;color:#e8e8ed;font-family:sans-serif;
            display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#121217;padding:40px;border-radius:16px;text-align:center}
            h1{color:#9146FF;margin-bottom:8px}p{color:#9d9dab}</style></head>
            <body><div class="card"><h1>PhoneCam</h1>
            <p>Servidor MJPEG activo en puerto $port</p>
            <p>Stream: <a href="/video" style="color:#9146FF">/video</a></p>
            </div></body></html>
        """.trimIndent()
        sendText(sock, 200, "text/html", html)
    }

    private fun respondMjpeg(sock: Socket) {
        val out = sock.getOutputStream()
        val header = (
            "HTTP/1.1 200 OK\r\n" +
            "Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY\r\n" +
            "Cache-Control: no-cache\r\n" +
            "Connection: close\r\n\r\n"
        )
        out.write(header.toByteArray())
        out.flush()

        // Enviar último frame conocido
        synchronized(frameLock) {
            latestFrame?.let { notifySingleFrame(out, it) }
        }
        // Los frames siguientes llegan vía notifyClients()
    }

    private fun notifySingleFrame(out: java.io.OutputStream, jpeg: ByteArray) {
        val header = (
            "--$BOUNDARY\r\n" +
            "Content-Type: image/jpeg\r\n" +
            "Content-Length: ${jpeg.size}\r\n\r\n"
        ).toByteArray()
        out.write(header)
        out.write(jpeg)
        out.write("\r\n".toByteArray())
        out.flush()
    }

    private fun respondStatus(sock: Socket, query: String) {
        val json = """
            {
                "role": "server",
                "model": "PhoneCam Android",
                "resolution": "${width}x${height}",
                "fps": 30,
                "video_size": "${width}x${height}",
                "ffc": "$facing",
                "port": $port,
                "signal": 100,
                "current_fps": 30,
                "earpiece": false
            }
        """.trimIndent()
        sendText(sock, 200, "application/json", json)
    }

    private fun respondFfc(sock: Socket, query: String) {
        val params = parseQuery(query)
        val set = params["set"] ?: ""
        facing = if (set == "on") "on" else "off"
        sendText(sock, 200, "text/plain", "Ok")
        Log.i(TAG, "Camera switched: ffc=$facing")
    }

    private fun respondVideoSize(sock: Socket, query: String) {
        val params = parseQuery(query)
        val set = params["set"] ?: ""
        if (set.contains("x")) {
            try {
                val parts = set.lowercase().split("x")
                width = parts[0].trim().toInt()
                height = parts[1].trim().toInt()
                sendText(sock, 200, "text/plain", "Ok")
                Log.i(TAG, "Resolution changed: ${width}x${height}")
            } catch (_: Exception) {
                sendText(sock, 400, "text/plain", "Bad Request")
            }
        } else {
            sendText(sock, 400, "text/plain", "Bad Request")
        }
    }

    private fun respondFps(sock: Socket, query: String) {
        // FPS is handled by capture interval; acknowledge but don't change.
        sendText(sock, 200, "text/plain", "Ok")
    }

    private fun respondShot(sock: Socket) {
        synchronized(frameLock) {
            val jpeg = latestFrame
            if (jpeg != null) {
                val out = sock.getOutputStream()
                val header = (
                    "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: image/jpeg\r\n" +
                    "Content-Length: ${jpeg.size}\r\n\r\n"
                )
                out.write(header.toByteArray())
                out.write(jpeg)
                out.flush()
            } else {
                sendText(sock, 503, "text/plain", "No frame available")
            }
        }
    }

    private fun respond404(sock: Socket) {
        sendText(sock, 404, "text/plain", "Not Found")
    }

    private fun sendText(sock: Socket, code: Int, contentType: String, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        val header = (
            "HTTP/1.1 $code ${httpStatus(code)}\r\n" +
            "Content-Type: $contentType; charset=utf-8\r\n" +
            "Content-Length: ${bytes.size}\r\n" +
            "Connection: close\r\n\r\n"
        )
        val out = sock.getOutputStream()
        out.write(header.toByteArray())
        out.write(bytes)
        out.flush()
    }

    private fun httpStatus(code: Int): String = when (code) {
        200 -> "OK"; 400 -> "Bad Request"; 404 -> "Not Found"; 503 -> "Service Unavailable"
        else -> "OK"
    }

    private fun parseQuery(query: String): Map<String, String> {
        if (query.isEmpty()) return emptyMap()
        return query.split("&").associate {
            val parts = it.split("=", limit = 2)
            parts[0] to (parts.getOrElse(1) { "" })
        }
    }
}

package com.phonecam.app

/**
 * Configuración global de la app Android PhoneCam.
 * Equivalente a config.py del cliente de escritorio.
 */
object AppConfig {
    /** Versión de la aplicación (debe coincidir con versionName en build.gradle). */
    const val APP_VERSION = "1.0.0"

    /** Repositorio de GitHub para auto-actualización ("usuario/repositorio"). */
    const val GITHUB_REPO = "kaluktr/phonecam"

    /** Nombre visible de la app. */
    const val APP_NAME = "PhoneCam"

    /** Puerto del servidor MJPEG. */
    const val DEFAULT_PORT = 8080
}

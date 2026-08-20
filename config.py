"""
config.py
=========

Configuración global del proyecto PhoneCam: versión, repositorio de GitHub
(para auto-actualización) y límites de la versión TRIAL vs PRO.
"""

# Versión actual de la aplicación. Debe coincidir con el tag del release de
# GitHub (p. ej. "v1.0.0") para que la auto-actualización funcione.
APP_VERSION = "1.0.0"

# Repositorio de GitHub en formato "usuario/repositorio". Cambiar por el real.
GITHUB_REPO = "kaluktr/phonecam"

# Nombre visible de la aplicación.
APP_NAME = "PhoneCam"

# --------------------------------------------------------------------------- #
#  Límites de la versión TRIAL                                                #
# --------------------------------------------------------------------------- #
# La versión de prueba permite hasta 720p @ 30 fps y solo conexión Wi-Fi.
# La versión PRO desbloquea la resolución/FPS máximos y el modo USB.
TRIAL_MAX_RES = "1280x720"
TRIAL_MAX_FPS = 30

# Precio de la licencia PRO (pago único).
PRO_PRICE_USD = 1

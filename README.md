# PhoneCam — Usa la cámara de tu teléfono como cámara web en Windows

Convierte la cámara de tu **Android** en una cámara web para tu PC. Incluye:

- **Cliente de escritorio en Python** (Tkinter + OpenCV) con GUI oscura
  (tema morado) e iconos de [Font Awesome](https://fontawesome.com/).
- **App Android propia** con servidor MJPEG, tema oscuro y compatibility total
  con los endpoints del cliente (reemplaza a IP Webcam).
- **Modo Wi-Fi**: captura el stream por la red local (IP + puerto).
- **Modo USB**: captura por cable mediante `adb forward` (requiere licencia PRO).
- **Cambio de cámara** frontal/trasera y **selección de resolución y FPS**.
- **Cámara virtual**: el teléfono aparece como webcam real en Discord/Zoom/Meet
  usando un **driver independiente** (Unity Capture, sin instalar OBS).
- **Licencia PRO**: pago único de 1 USD para desbloquear modo USB y resolución
  máxima. La TRIAL permite 720p@30fps en Wi-Fi.
- **Auto-actualización**: detecta nuevas versiones desde GitHub.

```
Teléfono (PhoneCam Android / IP Webcam) ── Wi-Fi ──┐
    │                                                ├──►  Cliente Python (OpenCV + Tkinter)
    └── USB ──► adb forward tcp:4747 tcp:8080 ──► 127.0.0.1:4747 ──┘
```

---

## 1. Requisitos

- **Python 3.9 o superior** (con la opción *Add Python to PATH* marcada).
  Descárgalo desde <https://www.python.org/downloads/>.
- Un teléfono **Android** (con la app PhoneCam propia o IP Webcam).
- Para el **modo USB**: *Android SDK Platform-Tools* (incluye `adb`) y
  licencia PRO activada.

### Instalar dependencias de Python

```powershell
pip install -r requirements.txt
```

También puedes instalarlas manualmente:

```powershell
pip install opencv-python Pillow numpy pyvirtualcam cryptography
```

> `tkinter` viene incluido en el Python oficial de Windows, no necesita
> instalación aparte.

---

## 2. App Android propia (PhoneCam)

Incluida en la carpeta `android/`. Es un reemplazo completo de IP Webcam con
la misma API de endpoints (compatibilidad total con el cliente de escritorio).

### Características

- Servidor MJPEG en puerto 8080 (mismos endpoints que IP Webcam).
- Selector de resolución (640x480 / 1280x720 / 1920x1080 / 2560x1440).
- Cambio de cámara frontal/trasera.
- Tema oscuro morado (misma paleta que el cliente de escritorio).
- Sin anuncios, sin dependencias externas, sin rastreo.

### Endpoints implementados

| Acción             | URL                                        |
|--------------------|--------------------------------------------|
| Video (MJPEG)      | `http://IP:8080/video`                     |
| Instantánea        | `http://IP:8080/shot.jpg`                  |
| Cámara frontal     | `http://IP:8080/settings/ffc?set=on`       |
| Cámara trasera     | `http://IP:8080/settings/ffc?set=off`      |
| Cambiar resolución | `http://IP:8080/settings/video_size?set=WxH` |
| Estado (JSON)      | `http://IP:8080/status.json`               |

### Compilar e instalar

1. Abre la carpeta `android/` en **Android Studio**.
2. Sincroniza Gradle y espera a que descargue las dependencias.
3. Conecta tu teléfono con Depuración USB activa.
4. Pulsa **Run** (▶) o genera un APK con **Build → Build APK**.
5. Instala el APK en tu teléfono.

---

## 3. Ejecutar el cliente de escritorio

```powershell
python webcam_client.py
```

### Modo Wi-Fi

1. Conecta el teléfono y el PC a la **misma red Wi-Fi**.
2. Abre PhoneCam Android y pulsa **Iniciar** (o IP Webcam → *Start server*).
3. En el cliente: selecciona **Wi-Fi**, escribe la **IP** y el **puerto**,
   y pulsa **Conectar**.

### Modo USB (requiere PRO)

1. Habilita la **Depuración USB** en el teléfono (ver sección 5).
2. Conecta el teléfono al PC con un cable USB.
3. Activa tu licencia PRO (pulsa el badge TRIAL → pega la clave).
4. Selecciona **USB** y pulsa **Conectar**.

### Cambiar de cámara y resolución/FPS

- Pulsa **Cambiar cámara** para alternar entre frontal y trasera.
- Usa los selects de **Resolución** y **FPS** para ajustar la calidad.
- Por defecto se aplican los mejores valores disponibles automáticamente.

### Cámara virtual (para Discord, Zoom, Meet, Teams...)

Al conectar, el teléfono aparece automáticamente como webcam real.

1. Instala **Unity Capture** desde
   <https://github.com/schellingb/UnityCapture#installation>
2. En Discord/Zoom elige **"Unity Video Capture"**.

---

## 4. Licencia PRO (pago único — 1 USD)

La versión **TRIAL** está limitada a:
- Máximo **720p @ 30 fps**.
- Solo modo **Wi-Fi**.

La versión **PRO** desbloquea:
- Resolución y FPS **máximos** (1080p60, 1440p, etc.).
- Modo **USB** (cable, sin latencia de Wi-Fi).

### Activar una licencia

1. Haz el pago de 1 USD (instrucciones del vendedor).
2. Recibirás una **clave de licencia**.
3. En el cliente de escritorio, haz clic en el badge **TRIAL** (arriba a la
   derecha).
4. Pega la clave y pulsa **Activar**.
5. Reinicia el cliente para aplicar todos los cambios.

### Generar licencias (administrador)

```powershell
python keygen.py cliente@email.com
```

Esto genera el par de claves y una licencia firmada. La clave pública
(`PUBLIC_KEY_HEX`) se pega en `licensing.py`.

---

## 5. Habilitar la Depuración USB (Android)

1. Ve a **Ajustes → Acerca del teléfono**.
2. Pulsa **7 veces** sobre **"Número de compilación"**.
3. Vuelve a **Ajustes → Sistema → Opciones de desarrollador**.
4. Activa **Depuración USB**.
5. Conecta el cable USB y acepta el diálogo **"¿Permitir depuración USB?"**.

### Instalar `adb` (Platform-Tools)

- Descarga **platform-tools** desde
  <https://developer.android.com/tools/releases/platform-tools>.
- Descomprime y agrégalo al PATH del sistema.
- Verifica con `adb devices`.

---

## 6. Auto-actualización

El cliente verifica automáticamente si hay una nueva versión en GitHub al
iniciarse. Si la hay, muestra un diálogo para abrir la página de descarga.

Para configurar el repositorio, edita `config.py`:

```python
GITHUB_REPO = "tu-usuario/phonecam"
```

Y crea releases en GitHub con tags como `v1.0.0`, `v1.1.0`, etc.

---

## 7. Solución de problemas

| Problema                                      | Solución |
|-----------------------------------------------|----------|
| "No se pudo abrir el stream"                  | Verifica IP/puerto, que la app esté activa y ambos en la misma red. |
| "No se encontró 'adb'"                        | Instala platform-tools y agrégalo al PATH. |
| "No se detectó ningún dispositivo Android"    | Activa Depuración USB y acepta el diálogo RSA. |
| Video con retardo                             | Baja la resolución o usa cable USB (requiere PRO). |
| Cámara virtual no aparece en Discord          | Instala Unity Capture y reinicia Discord. |
| Iconos no se ven                              | El cliente descarga `fa-solid-900.ttf` automáticamente. |
| USB no funciona                               | Activa tu licencia PRO (el modo USB es exclusivo PRO). |

---

## 8. Archivos del proyecto

```
phonecam/
├── webcam_client.py     # Cliente de escritorio (GUI + reproducción)
├── fa_icons.py          # Renderizado de iconos Font Awesome (Pillow)
├── config.py            # Configuración global (versión, límites TRIAL/PRO)
├── licensing.py         # Verificación offline de licencias PRO (Ed25519)
├── keygen.py            # Generador de licencias (herramienta admin)
├── updater.py           # Auto-actualización desde GitHub releases
├── requirements.txt     # Dependencias de Python
├── README.md            # Esta guía
└── android/             # App Android (PhoneCam)
    ├── app/
    │   ├── build.gradle
    │   └── src/main/
    │       ├── AndroidManifest.xml
    │       ├── java/com/phonecam/app/
    │       │   ├── MainActivity.kt
    │       │   └── MjpegServer.kt
    │       └── res/
    │           ├── layout/activity_main.xml
    │           ├── values/colors.xml
    │           ├── values/themes.xml
    │           └── drawable/
    ├── build.gradle
    ├── settings.gradle
    └── gradle.properties
```

## Licencias

- **Font Awesome Free**: licencia SIL OFL 1.1 (tipografía). Los iconos se
  descargan automáticamente para uso gratuito.
- El código de este proyecto es de libre uso.

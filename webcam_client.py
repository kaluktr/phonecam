"""
webcam_client.py
================

Cliente de escritorio (Windows / Linux / macOS) que usa la cámara de un
teléfono como cámara web. Recibe un stream MJPEG (o RTSP) a través de Wi-Fi o
por cable USB mediante redirección de puertos con ADB.

Aplicación móvil recomendada: "IP Webcam" (com.pas.webcam) de Pavel Khlebovich.
    - Stream de video MJPEG : http://<ip>:<puerto>/video
    - Instantánea            : http://<ip>:<puerto>/shot.jpg
    - Cambiar cámara         : http://<ip>:<puerto>/settings/ffc?set=on|off
                               (on = frontal, off = trasera)
    - Resolución             : http://<ip>:<puerto>/settings/video_size?set=WxH
    - FPS                    : http://<ip>:<puerto>/settings/fps?set=<n>

Modos de conexión:
    * Wi-Fi : conecta directamente a http://IP:puerto/video
    * USB   : ejecuta "adb forward tcp:<local> tcp:<puerto>" y lee desde
              http://127.0.0.1:<local>/video

Cámara virtual: al conectar, el stream se expone automáticamente como un
dispositivo de cámara virtual (Unity Capture / OBS Virtual Camera) para que
Discord/Zoom/Meet lo detecten. No requiere OBS; ver README.

Requisitos: ver requirements.txt y el README.md adjunto.
"""

import json
import os

# Silenciar los avisos del decodificador MJPEG de FFmpeg ("overread N").
# Son inofensivos (el video sigue bien) pero ensucian la consola; se deben
# fijar ANTES de importar cv2.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "16")

import queue
import shutil
import subprocess
import threading
import time
from urllib import request as urlrequest
from urllib.parse import quote, urlsplit

import cv2
from PIL import Image, ImageDraw, ImageFont, ImageTk

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
import webbrowser

import fa_icons

import config
import licensing
import updater

# ------------------------- Tema (inspirado en MULTICHAT) ------------------- #
APP_NAME = "PhoneCam"
BG = "#0a0a0d"              # bg-primary
BG_SECONDARY = "#121217"    # bg-secondary (tarjetas)
BG_TERTIARY = "#1a1a22"     # bg-tertiary (chips, campos)
BG_HOVER = "#22222d"        # hover
BG_INPUT = "#1e1e28"        # fondo de inputs
BORDER = "#282836"          # bordes
ACCENT = "#9146FF"          # acento (morado)
ACCENT_HOVER = "#7c3aed"
TEXT = "#e8e8ed"            # texto principal
TEXT_SECONDARY = "#9d9dab"
TEXT_MUTED = "#5c5c6e"
SUCCESS = "#16a34a"
ERROR = "#dc2626"
ERROR_TINT = "#2a1216"      # fondo rojo suave (hover de Desconectar)
VIDEO_BG = (10, 10, 13)
RADIUS = 14                 # radio de las esquinas redondeadas

MAX_W, MAX_H = 640, 480     # tamaño máximo de la previsualización

# Presets por defecto (se reemplazan por los reales al conectar).
RES_PRESETS = ["640x480", "1280x720", "1920x1080", "2560x1440"]
FPS_PRESETS = ["15", "30", "60"]

# Valores por defecto: los mejores disponibles (1080p @ 60 fps).
DEFAULT_RES = "1920x1080"
DEFAULT_FPS = "60"


def _system_font(root):
    """Elige 'Inter' si está instalada; si no, 'Segoe UI'."""
    families = set(tkfont.families(root))
    return "Inter" if "Inter" in families else "Segoe UI"


class RoundedPanel(tk.Canvas):
    """Panel con esquinas redondeadas (Canvas + polígono suavizado)."""

    def __init__(self, parent, radius=RADIUS, bg=BG_SECONDARY, outline=BORDER,
                 padx=16, pady=12, fill_x=False):
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0)
        self.radius = radius
        self.fill = bg
        self.outline = outline
        self.padx, self.pady = padx, pady
        self.fill_x = fill_x

        self.inner = tk.Frame(self, bg=bg)
        self._win = self.create_window(padx, pady, anchor="nw", window=self.inner)
        self.bind("<Configure>", self._on_configure)
        self.inner.bind("<Configure>", lambda e: self._sync_size())

    def _on_configure(self, event):
        if self.fill_x and event.width > 1:
            self.itemconfigure(self._win, width=max(event.width - 2 * self.padx, 1))
        self._draw()

    def _sync_size(self, event=None):
        h = self.inner.winfo_reqheight() + 2 * self.pady
        if self.fill_x:
            self.configure(height=h)
        else:
            w = self.inner.winfo_reqwidth() + 2 * self.padx
            self.configure(width=w, height=h)

    def _draw(self):
        self.delete("bg")
        w = max(self.winfo_width(), 2)
        h = max(self.winfo_height(), 2)
        self.create_polygon(self._points(w, h), smooth=True,
                            fill=self.fill, outline=self.outline, tags="bg")
        self.tag_lower("bg")

    def _points(self, w, h):
        r = min(self.radius, w / 2, h / 2)
        x1, y1, x2, y2 = 0, 0, w, h
        return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1,
                x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
                x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class PhoneCamApp:
    """Ventana principal y lógica de reproducción del cliente."""

    def __init__(self, root):
        self.root = root
        self.FONT = _system_font(root)
        self.root.title(f"{APP_NAME} — Cámara web desde el teléfono")
        self.root.configure(bg=BG)
        self.root.minsize(760, 680)

        # Estado de la conexión.
        self.connected = False
        self.connecting = False
        self.mode = "wifi"              # "wifi" | "usb"
        self.front_camera = None        # True/False/None (desconocido)

        # Licencia (TRIAL vs PRO).
        self.is_pro = licensing.is_pro()

        # Recursos de video.
        self.cap = None
        self.stream_url = None
        self.base_url = None
        self.running = threading.Event()
        self.worker = None
        self.frame_queue = queue.Queue(maxsize=1)
        self.reconnect_pending = False
        self.consecutive_failures = 0
        self._usb_forward = None        # (puerto_local, puerto_teléfono)

        # Cámara virtual (se activa automáticamente al conectar).
        self.virtual_enabled = False
        self.vcam_thread = None
        self._frame_lock = threading.Lock()
        self._latest_frame = None

        # Contador de FPS.
        self._fps_count = 0
        self._fps_t0 = time.monotonic()

        # Referencias que evitan que el recolector de basura borre las imágenes.
        self.icon_refs = []
        self.current_photo = None
        self.placeholder = None

        # Variables de Tkinter.
        self.ip_var = tk.StringVar(value="")
        self.port_var = tk.StringVar(value="8080")
        self.usb_local_port_var = tk.StringVar(value="4747")
        self.phone_port_var = tk.StringVar(value="8080")
        self.res_var = tk.StringVar(value=DEFAULT_RES)
        self.fps_var = tk.StringVar(value=DEFAULT_FPS)

        self._setup_style()
        self._build_ui()
        self._update_controls()
        self._refresh_license_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_frame_loop()
        self._check_updates_async()

    # ------------------------------------------------------------------ #
    #  Estilo (ttk oscuro)                                                #
    # ------------------------------------------------------------------ #
    def _setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=BG_INPUT, background=BG_TERTIARY,
                        foreground=TEXT, arrowcolor=TEXT_SECONDARY,
                        bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, insertcolor=TEXT,
                        selectbackground=ACCENT, selectforeground="#ffffff",
                        padding=3)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG_INPUT)],
                  foreground=[("readonly", TEXT)],
                  bordercolor=[("focus", ACCENT)])
        self.root.option_add("*TCombobox*Listbox.background", BG_TERTIARY)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    # ------------------------------------------------------------------ #
    #  Construcción de la interfaz                                        #
    # ------------------------------------------------------------------ #
    def _icon(self, name, size=18, color=TEXT_SECONDARY):
        img = fa_icons.photo(self.root, name, size, color)
        if img is not None:
            self.icon_refs.append(img)
        return img

    def _button(self, parent, text, icon, bg, fg, command, border=None,
                active_bg=None, active_fg=None):
        img = self._icon(icon, 15, fg)
        if border is None:
            border = bg
        if active_bg is None:
            active_bg = bg
        if active_fg is None:
            active_fg = fg
        return tk.Button(parent, text=text, image=img, compound="left",
                         command=command, font=(self.FONT, 10, "bold"),
                         bg=bg, fg=fg, activebackground=active_bg,
                         activeforeground=active_fg, relief="flat", bd=0,
                         padx=14, pady=7, cursor="hand2",
                         highlightthickness=1, highlightbackground=border)

    def _small(self, parent, text, bg=BG_SECONDARY):
        """Etiqueta pequeña en mayúsculas (estilo MULTICHAT)."""
        return tk.Label(parent, text=text, font=(self.FONT, 8, "bold"),
                        bg=bg, fg=TEXT_MUTED)

    def _field(self, parent, label, var, row):
        tk.Label(parent, text=label, bg=BG_SECONDARY, fg=TEXT_SECONDARY,
                 font=(self.FONT, 9)).grid(row=row, column=0, sticky="w",
                                           padx=(0, 8), pady=3)
        entry = tk.Entry(parent, textvariable=var, width=22,
                         font=(self.FONT, 10), relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT, bg=BG_INPUT, fg=TEXT,
                         insertbackground=TEXT)
        entry.grid(row=row, column=1, sticky="w", padx=(0, 16))

    def _make_placeholder(self, message):
        img = Image.new("RGB", (MAX_W, MAX_H), VIDEO_BG)
        draw = ImageDraw.Draw(img)
        font = self._ui_font(22)
        w = draw.textlength(message, font=font)
        draw.text(((MAX_W - w) / 2, MAX_H / 2 - 12), message,
                  font=font, fill=(92, 92, 110))
        return ImageTk.PhotoImage(img)

    @staticmethod
    def _ui_font(size):
        candidates = [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _build_ui(self):
        main = tk.Frame(self.root, bg=BG, padx=24, pady=16)
        main.pack(fill="both", expand=True)

        # --- Cabecera (título + estado) ---
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(side="left")
        tk.Label(title_row, text="Phone", font=(self.FONT, 16, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(title_row, text="Cam", font=(self.FONT, 16, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")

        status_row = tk.Frame(header, bg=BG)
        status_row.pack(side="right")
        self.status_dot = tk.Label(status_row, text="●", font=(self.FONT, 10),
                                   bg=BG, fg=TEXT_MUTED)
        self.status_dot.pack(side="left", padx=(0, 5))
        self.status_label = tk.Label(status_row, text="Desconectado",
                                     font=(self.FONT, 10), bg=BG,
                                     fg=TEXT_MUTED)
        self.status_label.pack(side="left")

        # Badge PRO / TRIAL (clic para abrir diálogo de licencia).
        self.pro_btn = tk.Button(header, text="TRIAL", font=(self.FONT, 8, "bold"),
                                 bg=BG_TERTIARY, fg=TEXT_MUTED, relief="flat",
                                 bd=0, padx=10, pady=2, cursor="hand2",
                                 highlightthickness=1, highlightbackground=BORDER,
                                 command=self._open_license_dialog)
        self.pro_btn.pack(side="right", padx=(0, 12))

        # --- Panel compacto de controles ---
        panel = RoundedPanel(main, fill_x=True, pady=12)
        panel.pack(fill="x")

        # Fila superior: modo (izq) + resolución/FPS (der).
        top = tk.Frame(panel.inner, bg=BG_SECONDARY)
        top.pack(fill="x")

        left = tk.Frame(top, bg=BG_SECONDARY)
        left.pack(side="left")
        self._small(left, "MODO").pack(anchor="w", pady=(0, 4))
        chips = tk.Frame(left, bg=BG_SECONDARY)
        chips.pack(side="left")
        self.mode_buttons = {}
        for value, label, icon in (("wifi", "Wi-Fi", "wifi"),
                                   ("usb", "USB", "plug")):
            img_normal = self._icon(icon, 14, TEXT_SECONDARY)
            img_active = self._icon(icon, 14, "#ffffff")
            btn = tk.Button(chips, text=label, image=img_normal, compound="left",
                            command=lambda v=value: self._set_mode(v),
                            font=(self.FONT, 9), relief="flat", bd=0,
                            padx=12, pady=5, cursor="hand2",
                            highlightthickness=1)
            btn._img_normal = img_normal
            btn._img_active = img_active
            btn.pack(side="left", padx=(0, 6))
            self.mode_buttons[value] = btn

        right = tk.Frame(top, bg=BG_SECONDARY)
        right.pack(side="right")
        self._small(right, "RESOLUCIÓN").pack(anchor="w", pady=(0, 4))
        self.res_combo = ttk.Combobox(right, textvariable=self.res_var,
                                      values=RES_PRESETS, width=12,
                                      state="readonly",
                                      style="Dark.TCombobox")
        self.res_combo.pack(anchor="w", pady=(0, 4))
        self._small(right, "FPS").pack(anchor="w", pady=(6, 4))
        self.fps_combo = ttk.Combobox(right, textvariable=self.fps_var,
                                      values=FPS_PRESETS, width=6,
                                      state="readonly",
                                      style="Dark.TCombobox")
        self.fps_combo.pack(anchor="w")

        self.res_combo.bind("<<ComboboxSelected>>",
                            self._on_camera_setting_change)
        self.fps_combo.bind("<<ComboboxSelected>>",
                            self._on_camera_setting_change)

        # Fila de parámetros (dinámica según el modo).
        self.params_body = tk.Frame(panel.inner, bg=BG_SECONDARY)
        self.params_body.pack(fill="x", pady=(12, 0))

        # Fila de acciones.
        actions = tk.Frame(panel.inner, bg=BG_SECONDARY)
        actions.pack(fill="x", pady=(14, 0))
        self.btn_connect = self._button(actions, "Conectar", "play",
                                        ACCENT, "#ffffff", self.connect,
                                        active_bg=ACCENT_HOVER)
        self.btn_connect.pack(side="left", padx=(0, 8))
        self.btn_disconnect = self._button(actions, "Desconectar", "power",
                                           BG_TERTIARY, ERROR, self.disconnect,
                                           border=ERROR, active_bg=ERROR_TINT)
        self.btn_disconnect.pack(side="left", padx=(0, 8))
        self.btn_switch = self._button(actions, "Cambiar cámara", "swap",
                                       BG_TERTIARY, TEXT, self.switch_camera,
                                       border=BORDER, active_bg=BG_HOVER)
        self.btn_switch.pack(side="left")

        # --- Visor de video (panel redondeado) ---
        self.placeholder = self._make_placeholder("Sin señal de video")
        video_panel = RoundedPanel(main, radius=RADIUS, padx=8, pady=8)
        video_panel.pack(expand=True)
        self.video_label = tk.Label(video_panel.inner, image=self.placeholder,
                                    bg="#0a0a0d", bd=0)
        self.video_label.pack()
        self.current_photo = self.placeholder

        # --- Barra de estado (log + FPS) ---
        statusbar = tk.Frame(main, bg=BG)
        statusbar.pack(fill="x", pady=(12, 0))
        self.log_var = tk.StringVar(value="Listo. Selecciona el modo y conecta.")
        tk.Label(statusbar, textvariable=self.log_var, bg=BG, fg=TEXT_MUTED,
                 font=(self.FONT, 9), anchor="w").pack(side="left")
        self.fps_label = tk.Label(statusbar, text="", bg=BG, fg=TEXT_MUTED,
                                  font=(self.FONT, 9))
        self.fps_label.pack(side="right")

        self._set_mode("wifi")

    # ------------------------------------------------------------------ #
    #  Selección de modo y campos dinámicos                               #
    # ------------------------------------------------------------------ #
    def _set_mode(self, value):
        if value == "usb" and not self.is_pro:
            messagebox.showinfo(
                "Modo USB — PRO",
                "El modo USB está disponible solo en la versión PRO.\n\n"
                f"Precio: 1 USD (pago único).\n\n"
                "Haz clic en el botón TRIAL para activar tu licencia.")
            return
        self.mode = value
        for v, btn in self.mode_buttons.items():
            active = (v == value)
            btn.configure(
                image=btn._img_active if active else btn._img_normal,
                bg=ACCENT if active else BG_TERTIARY,
                fg="#ffffff" if active else TEXT_SECONDARY,
                activebackground=ACCENT if active else BG_HOVER,
                activeforeground="#ffffff" if active else TEXT,
                highlightbackground=ACCENT if active else BORDER)
        self._refresh_connection_fields()

    def _refresh_connection_fields(self):
        for child in self.params_body.winfo_children():
            child.destroy()

        if self.mode == "wifi":
            self._field(self.params_body, "IP del teléfono", self.ip_var, 0)
            self._field(self.params_body, "Puerto", self.port_var, 1)
            hint = ("La IP aparece en IP Webcam (ej. 192.168.1.50). "
                    "Puerto: 8080. También acepta una URL completa.")
        else:
            self._field(self.params_body, "Puerto local (PC)",
                        self.usb_local_port_var, 0)
            self._field(self.params_body, "Puerto teléfono",
                        self.phone_port_var, 1)
            hint = ("ADB redirige tcp:<local> -> tcp:<puerto>. Activa la "
                    "Depuración USB y conecta el cable.")

        tk.Label(self.params_body, text=hint, bg=BG_SECONDARY, fg=TEXT_MUTED,
                 font=(self.FONT, 8), justify="left",
                 wraplength=560).grid(row=2, column=0, columnspan=4,
                                      sticky="w", pady=(6, 0))

    # ------------------------------------------------------------------ #
    #  Conexión / desconexión                                             #
    # ------------------------------------------------------------------ #
    def connect(self):
        if self.connected or self.connecting:
            return
        if self.mode == "usb" and not self.is_pro:
            messagebox.showinfo(
                "Modo USB — PRO",
                "El modo USB está disponible solo en la versión PRO.\n\n"
                "Haz clic en el botón TRIAL para activar tu licencia.")
            return
        params = {
            "mode": self.mode,
            "ip": self.ip_var.get().strip(),
            "port": self.port_var.get().strip(),
            "local": self.usb_local_port_var.get().strip(),
            "phone": self.phone_port_var.get().strip(),
        }
        self.connecting = True
        self._set_status("Conectando…", "busy")
        self._update_controls()
        threading.Thread(target=self._connect_worker, args=(params,),
                         daemon=True).start()

    def _connect_worker(self, params):
        try:
            base_url, stream_url = self._resolve_target(params)
            cap = cv2.VideoCapture(stream_url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                raise ConnectionError(f"No se pudo abrir el stream:\n{stream_url}")
            result = (True, cap, base_url, stream_url, None)
        except Exception as exc:
            result = (False, None, None, None, str(exc))
        self.root.after(0, self._finish_connect, result)

    def _resolve_target(self, params):
        if params["mode"] == "usb":
            return self._setup_usb(params)
        return self._build_wifi_target(params)

    def _build_wifi_target(self, params):
        host = params["ip"]
        port = params["port"]
        if not host:
            raise ValueError("Introduce la dirección IP del teléfono.")
        if "://" in host:
            url = host
            parts = urlsplit(url)
            if parts.scheme == "rtsp":
                base = f"http://{parts.hostname}:{parts.port or 8080}"
            else:
                base = f"{parts.scheme}://{parts.netloc}"
            return base, url
        if not port:
            port = "8080"
        return f"http://{host}:{port}", f"http://{host}:{port}/video"

    def _setup_usb(self, params):
        adb = shutil.which("adb")
        if not adb:
            raise RuntimeError(
                "No se encontró 'adb'. Instala Android SDK Platform-Tools y "
                "agrégalo al PATH (ver README).")

        local = params["local"] or "4747"
        phone = params["phone"] or "8080"

        proc = subprocess.run([adb, "devices"], capture_output=True, text=True)
        devices, unauthorized = self._parse_adb_devices(proc.stdout)
        if not devices:
            if unauthorized:
                raise RuntimeError(
                    "Dispositivo no autorizado. Acepta el diálogo "
                    "'¿Permitir depuración USB?' en el teléfono.")
            raise RuntimeError(
                "No se detectó ningún dispositivo Android. Conecta el cable "
                "USB y activa la Depuración USB.")

        subprocess.run([adb, "-s", devices[0], "forward",
                        f"tcp:{local}", f"tcp:{phone}"],
                       capture_output=True, text=True, check=True)
        self._usb_forward = (local, phone)

        base = f"http://127.0.0.1:{local}"
        return base, f"{base}/video"

    @staticmethod
    def _parse_adb_devices(stdout):
        devices, unauthorized = [], False
        for line in stdout.splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            if parts[1] == "device":
                devices.append(parts[0])
            elif parts[1] == "unauthorized":
                unauthorized = True
        return devices, unauthorized

    def _finish_connect(self, result):
        self.connecting = False
        ok, cap, base_url, stream_url, error = result
        if not ok:
            self._set_status("Error de conexión", "error")
            self._update_controls()
            messagebox.showerror("Error de conexión", error)
            return

        self.cap = cap
        self.base_url = base_url
        self.stream_url = stream_url
        self.connected = True
        self.consecutive_failures = 0
        self._drain_queue()
        self.running.set()

        self.worker = threading.Thread(target=self._capture_loop, daemon=True)
        self.worker.start()

        self._set_status(f"Conectado — {stream_url}", "ok")
        self._update_controls()
        self._query_camera_info_async()
        self._start_virtual()          # cámara virtual automática

    def disconnect(self):
        if not self.connected:
            return
        self.running.clear()
        self.connected = False
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self._remove_usb_forward()
        self._drain_queue()
        self._clear_video()
        self._stop_virtual()
        with self._frame_lock:
            self._latest_frame = None
        self._set_status("Desconectado", "idle")
        self._update_controls()

    def _remove_usb_forward(self):
        if self._usb_forward:
            local, _phone = self._usb_forward
            adb = shutil.which("adb")
            if adb:
                subprocess.run([adb, "forward", "--remove", f"tcp:{local}"],
                               capture_output=True, text=True)
            self._usb_forward = None

    def _drain_queue(self):
        try:
            while True:
                self.frame_queue.get_nowait()
        except queue.Empty:
            pass

    # ------------------------------------------------------------------ #
    #  Captura y visualización de video                                    #
    # ------------------------------------------------------------------ #
    def _capture_loop(self):
        """Bucle en segundo plano. Solo conserva el frame más reciente."""
        while self.running.is_set():
            if self.reconnect_pending:
                self.reconnect_pending = False
                new_cap = cv2.VideoCapture(self.stream_url)
                new_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if new_cap.isOpened():
                    old = self.cap
                    self.cap = new_cap
                    if old is not None:
                        try:
                            old.release()
                        except Exception:
                            pass
                continue

            cap = self.cap
            if cap is None or not cap.isOpened():
                time.sleep(0.02)
                continue

            try:
                ret, frame = cap.read()
            except Exception:
                ret, frame = False, None

            if not ret or frame is None:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 40:
                    self.consecutive_failures = 0
                    self.reconnect_pending = True
                time.sleep(0.02)
                continue

            self.consecutive_failures = 0
            with self._frame_lock:
                self._latest_frame = frame
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def _update_frame_loop(self):
        if self.connected:
            try:
                frame = self.frame_queue.get_nowait()
            except queue.Empty:
                frame = None
            if frame is not None:
                self._display(frame)

        now = time.monotonic()
        dt = now - self._fps_t0
        if dt >= 1.0:
            fps = self._fps_count / dt if dt > 0 else 0
            self._fps_count = 0
            self._fps_t0 = now
            self.fps_label.configure(
                text=f"{fps:.0f} fps" if self.connected else "")

        self.root.after(10, self._update_frame_loop)

    def _display(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        scale = min(MAX_W / w, MAX_H / h)
        if scale < 1.0:
            w2, h2 = int(w * scale), int(h * scale)
            frame_bgr = cv2.resize(frame_bgr, (w2, h2),
                                   interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.current_photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.video_label.configure(image=self.current_photo)
        self._fps_count += 1

    def _clear_video(self):
        self.current_photo = self.placeholder
        self.video_label.configure(image=self.placeholder)

    # ------------------------------------------------------------------ #
    #  Ajustes de cámara (resolución / FPS) y estado frontal/trasera      #
    # ------------------------------------------------------------------ #
    def _query_camera_info_async(self):
        threading.Thread(target=self._query_camera_info, daemon=True).start()

    def _query_camera_info(self):
        front = cur_res = cur_fps = avail_res = avail_fps = None
        if self.base_url:
            try:
                url = f"{self.base_url}/status.json?show_avail=1"
                with urlrequest.urlopen(url, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                cur = data.get("curvals", {})
                avail = data.get("avail", {})
                front = cur.get("ffc") == "on"
                cur_res = cur.get("video_size")
                cur_fps = cur.get("fps")
                avail_res = avail.get("video_size")
                avail_fps = avail.get("fps")
            except Exception:
                pass
        self.root.after(0, self._apply_camera_info,
                        front, cur_res, cur_fps, avail_res, avail_fps)

    def _apply_camera_info(self, front, cur_res, cur_fps, avail_res, avail_fps):
        if front is not None:
            self.front_camera = front
            self._log("Cámara actual: " + ("frontal" if front else "trasera"))

        res_values = [str(r) for r in avail_res] if avail_res else list(RES_PRESETS)
        fps_values = [str(f) for f in avail_fps] if avail_fps else list(FPS_PRESETS)
        res_values = self._trial_filter_values(res_values, "res")
        fps_values = self._trial_filter_values(fps_values, "fps")
        self.res_combo.configure(values=res_values)
        self.fps_combo.configure(values=fps_values)

        best_res = max(res_values, key=self._res_area) if res_values else config.TRIAL_MAX_RES
        best_fps = max(fps_values, key=self._to_int) if fps_values else str(config.TRIAL_MAX_FPS)
        best_res, best_fps = self._trial_clamp(best_res, best_fps)
        self.res_var.set(best_res)
        self.fps_var.set(best_fps)

        if str(cur_res) != best_res or str(cur_fps) != best_fps:
            threading.Thread(target=self._apply_camera_settings,
                             daemon=True).start()

    @staticmethod
    def _res_area(res):
        try:
            w, h = str(res).lower().replace(" ", "").split("x")
            return int(w) * int(h)
        except Exception:
            return 0

    @staticmethod
    def _to_int(value):
        try:
            return int(str(value))
        except Exception:
            return 0

    def _trial_clamp(self, res, fps):
        """En TRIAL, limita a 720p y 30 fps."""
        if self.is_pro:
            return res, fps
        max_area = self._res_area(config.TRIAL_MAX_RES)
        if self._res_area(res) > max_area:
            res = config.TRIAL_MAX_RES
        if self._to_int(fps) > config.TRIAL_MAX_FPS:
            fps = str(config.TRIAL_MAX_FPS)
        return res, fps

    def _trial_filter_values(self, values, key):
        """Filtra una lista de valores de resolución/FPS según los límites del TRIAL."""
        if self.is_pro:
            return values
        if key == "res":
            max_area = self._res_area(config.TRIAL_MAX_RES)
            return [v for v in values if self._res_area(v) <= max_area]
        elif key == "fps":
            return [v for v in values if self._to_int(v) <= config.TRIAL_MAX_FPS]
        return values

    def _on_camera_setting_change(self, event=None):
        if not self.connected:
            self._log("Conéctate para aplicar la resolución/FPS.")
            return
        threading.Thread(target=self._apply_camera_settings, daemon=True).start()

    def _apply_camera_settings(self):
        res = self.res_var.get().strip()
        fps = self.fps_var.get().strip()
        res, fps = self._trial_clamp(res, fps)
        errors = []
        if self.base_url:
            try:
                self._set_setting("video_size", res)
            except Exception as exc:
                errors.append(f"resolución: {exc}")
            try:
                self._set_setting("fps", fps)
            except Exception as exc:
                errors.append(f"fps: {exc}")
        self.root.after(0, self._after_camera_settings, res, fps, errors)

    def _set_setting(self, key, value):
        url = f"{self.base_url}/settings/{key}?set={quote(str(value))}"
        with urlrequest.urlopen(url, timeout=6) as resp:
            text = resp.read().decode("utf-8", "replace")
        if "Ok" not in text:
            raise RuntimeError(text.strip()[:60])

    def _after_camera_settings(self, res, fps, errors):
        self.reconnect_pending = True
        if not errors:
            self._log(f"Cámara configurada: {res} @ {fps} fps")
        else:
            self._log("Cambios parciales — " + "; ".join(errors))

    def switch_camera(self):
        if not self.connected:
            messagebox.showinfo(APP_NAME, "Conéctate primero al teléfono.")
            return
        if not self.base_url:
            messagebox.showwarning(APP_NAME,
                                   "El cambio de cámara no está disponible "
                                   "para este stream.")
            return
        current_front = self.front_camera if self.front_camera is not None else False
        target_front = not current_front
        threading.Thread(target=self._switch_worker, args=(target_front,),
                         daemon=True).start()

    def _switch_worker(self, target_front):
        value = "on" if target_front else "off"
        try:
            with urlrequest.urlopen(f"{self.base_url}/settings/ffc?set={value}",
                                    timeout=6) as resp:
                text = resp.read().decode("utf-8", "replace")
            ok = "Ok" in text
        except Exception as exc:
            ok, text = False, str(exc)
        self.root.after(0, self._after_switch, ok, target_front, text)

    def _after_switch(self, ok, target_front, text):
        if ok:
            self.front_camera = target_front
            self.reconnect_pending = True
            self._log("Cámara cambiada a: " +
                      ("frontal" if target_front else "trasera"))
        else:
            self._log("No se pudo cambiar la cámara: " + text)

    # ------------------------------------------------------------------ #
    #  Cámara virtual (automática, sin OBS: usa Unity Capture)            #
    # ------------------------------------------------------------------ #
    def _start_virtual(self):
        """Activa la cámara virtual en segundo plano (no bloquea la UI)."""
        if self.virtual_enabled:
            return
        self.virtual_enabled = True
        self.vcam_thread = threading.Thread(target=self._virtual_loop,
                                            daemon=True)
        self.vcam_thread.start()

    def _virtual_loop(self):
        cam = None
        size = None
        try:
            import pyvirtualcam

            while self.virtual_enabled and self.running.is_set():
                with self._frame_lock:
                    frame = self._latest_frame
                if frame is None:
                    time.sleep(0.02)
                    continue

                h, w = frame.shape[:2]
                if cam is None or size != (w, h):
                    if cam is not None:
                        cam.close()
                    cam = pyvirtualcam.Camera(
                        width=w, height=h, fps=30,
                        fmt=pyvirtualcam.PixelFormat.BGR)
                    size = (w, h)
                    device = getattr(cam, "device", "cámara virtual")
                    self.root.after(
                        0, self._log,
                        f"Cámara virtual activa: {device} ({w}x{h})")
                cam.send(frame)
                cam.sleep_until_next_frame()
        except Exception as exc:
            self.root.after(0, self._virtual_failed, str(exc))
        finally:
            if cam is not None:
                try:
                    cam.close()
                except Exception:
                    pass

    def _virtual_failed(self, error):
        if self.virtual_enabled:
            self.virtual_enabled = False
            self._log("Cámara virtual no disponible. Instala Unity Capture "
                      "(ver README).")

    def _stop_virtual(self):
        self.virtual_enabled = False

    # ------------------------------------------------------------------ #
    #  Utilidades de estado                                               #
    # ------------------------------------------------------------------ #
    def _set_status(self, text, state="idle"):
        color = {"idle": TEXT_MUTED, "ok": SUCCESS,
                 "busy": ACCENT, "error": ERROR}.get(state, TEXT_MUTED)
        self.status_dot.configure(fg=color)
        self.status_label.configure(text=text, fg=color)

    def _log(self, text):
        self.log_var.set(text)

    def _update_controls(self):
        self.btn_connect.configure(
            state="normal" if (not self.connected and not self.connecting)
            else "disabled")
        self.btn_disconnect.configure(
            state="normal" if self.connected else "disabled")
        self.btn_switch.configure(
            state="normal" if self.connected else "disabled")

    # ------------------------------------------------------------------ #
    #  Licencia PRO / TRIAL                                               #
    # ------------------------------------------------------------------ #
    def _refresh_license_ui(self):
        """Actualiza el badge del botón de licencia y el estado USB."""
        if self.is_pro:
            self.pro_btn.configure(text="PRO", bg=ACCENT, fg="#ffffff",
                                   highlightbackground=ACCENT)
        else:
            self.pro_btn.configure(text="TRIAL", bg=BG_TERTIARY,
                                   fg=TEXT_MUTED, highlightbackground=BORDER)
        # El chip USB se ve "triste" si no es PRO.
        usb_btn = self.mode_buttons.get("usb")
        if usb_btn and not self.is_pro:
            usb_btn.configure(state="normal")
            usb_btn.configure(fg=TEXT_MUTED)

    def _open_license_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Activar licencia PRO")
        dlg.configure(bg=BG_SECONDARY)
        dlg.geometry("440x310")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="Activar PhoneCam PRO", font=(self.FONT, 14, "bold"),
                 bg=BG_SECONDARY, fg=TEXT).pack(pady=(18, 4))
        tk.Label(dlg, text="Pega tu clave de licencia (recibida tras el pago de 1 USD).",
                 bg=BG_SECONDARY, fg=TEXT_SECONDARY,
                 font=(self.FONT, 9)).pack(pady=(0, 12))

        key_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=key_var, width=48, font=(self.FONT, 9),
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT,
                         bg=BG_INPUT, fg=TEXT, insertbackground=TEXT)
        entry.pack(padx=20, pady=(0, 12))
        entry.focus_set()

        result_var = tk.StringVar()
        result_lbl = tk.Label(dlg, textvariable=result_var, bg=BG_SECONDARY,
                              font=(self.FONT, 9), fg=TEXT_MUTED, wraplength=380)
        result_lbl.pack(pady=(0, 8))

        def _activate():
            key = key_var.get().strip()
            if not key:
                result_var.set("Introduce una clave válida.")
                result_lbl.configure(fg=ERROR)
                return
            if licensing.activate(key):
                self.is_pro = True
                self._refresh_license_ui()
                result_var.set("¡Licencia activada! Reinicia para ver todos los cambios.")
                result_lbl.configure(fg=SUCCESS)
            else:
                result_var.set("Clave inválida o no corresponde al plan PRO.")
                result_lbl.configure(fg=ERROR)

        btn_frame = tk.Frame(dlg, bg=BG_SECONDARY)
        btn_frame.pack(pady=(4, 12))
        tk.Button(btn_frame, text="Activar", font=(self.FONT, 10, "bold"),
                  bg=ACCENT, fg="#ffffff", activebackground=ACCENT_HOVER,
                  relief="flat", bd=0, padx=20, pady=6, cursor="hand2",
                  command=_activate).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Cerrar", font=(self.FONT, 10),
                  bg=BG_TERTIARY, fg=TEXT_SECONDARY, relief="flat", bd=0,
                  padx=16, pady=6, cursor="hand2",
                  command=dlg.destroy).pack(side="left")

    # ------------------------------------------------------------------ #
    #  Auto-actualización                                                 #
    # ------------------------------------------------------------------ #
    def _check_updates_async(self):
        threading.Thread(target=self._do_check_updates, daemon=True).start()

    def _do_check_updates(self):
        has, latest, url, body = updater.check_for_update()
        if has:
            self.root.after(0, self._prompt_update, latest, url)

    def _prompt_update(self, version, url):
        answer = messagebox.askyesno(
            "Actualización disponible",
            f"PhoneCam {version} está disponible.\n\n"
            "¿Abrir la página de descarga en tu navegador?")
        if answer and url:
            webbrowser.open(url)

    def _on_close(self):
        self.running.clear()
        self.virtual_enabled = False
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self._remove_usb_forward()
        self.root.destroy()


def main():
    root = tk.Tk()
    PhoneCamApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


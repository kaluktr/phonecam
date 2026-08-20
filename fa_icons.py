"""
fa_icons.py
===========

Utilidad para dibujar iconos de Font Awesome (variante "Solid" gratuita)
dentro de una GUI de Tkinter.

Cómo funciona:
    - Busca el archivo "fa-solid-900.ttf" junto a este script o en la
      carpeta "assets".
    - Si no lo encuentra, intenta descargarlo automáticamente desde un CDN
      oficial (Cloudflare / jsDelivr) o desde el repositorio de Font Awesome.
    - Renderiza cada glifo con Pillow y lo convierte a ImageTk.PhotoImage.
    - Si la tipografía no está disponible, devuelve None para que la interfaz
      pueda recurrir a botones únicamente de texto.

Font Awesome Free se distribuye bajo la licencia SIL OFL 1.1 (uso gratuito).
"""

import os
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageTk

# Nombre del archivo de tipografía esperado.
FONT_FILENAME = "fa-solid-900.ttf"

# URLs candidatas para la descarga automática de la tipografía gratuita.
FONT_URLS = [
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/webfonts/fa-solid-900.ttf",
    "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.2/webfonts/fa-solid-900.ttf",
    "https://raw.githubusercontent.com/FortAwesome/Font-Awesome/6.x/webfonts/fa-solid-900.ttf",
]

# Mapa nombre -> punto de código Unicode (Font Awesome Free 6, estilo solid).
ICONS = {
    "wifi": 0xF1EB,      # fa-wifi
    "usb": 0xF287,       # fa-usb
    "camera": 0xF030,    # fa-camera
    "video": 0xF03D,     # fa-video
    "broadcast": 0xF519,  # fa-tower-broadcast
    "plug": 0xF1E6,      # fa-plug
    "power": 0xF011,     # fa-power-off
    "swap": 0xF362,      # fa-right-left
    "phone": 0xF10B,     # fa-mobile
    "info": 0xF05A,      # fa-circle-info
    "play": 0xF04B,      # fa-play
    "stop": 0xF04D,      # fa-stop
    "refresh": 0xF021,   # fa-arrows-rotate
    "warning": 0xF071,   # fa-triangle-exclamation
    "link": 0xF0C1,      # fa-link
    "check": 0xF00C,     # fa-check
}

_font_path_cache = None


def _candidate_paths():
    """Rutas locales donde podría encontrarse la tipografía."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, FONT_FILENAME),
        os.path.join(here, "assets", FONT_FILENAME),
    ]


def _download_font():
    """Descarga la tipografía y devuelve su ruta si tiene éxito (o None)."""
    dest = _candidate_paths()[0]
    for url in FONT_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            # Comprobación mínima: una TTF real pesa bastante más de 100 KB.
            if os.path.getsize(dest) > 100_000:
                return dest
        except Exception:
            continue
    return None


def font_path():
    """Devuelve la ruta de fa-solid-900.ttf, descargándola si hace falta."""
    global _font_path_cache
    if _font_path_cache:
        return _font_path_cache
    for path in _candidate_paths():
        if os.path.exists(path):
            _font_path_cache = path
            return path
    _font_path_cache = _download_font()
    return _font_path_cache


def _hex_to_rgb(color):
    """Convierte '#rrggbb' en una tupla (r, g, b)."""
    color = (color or "#2b3a4a").lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def render(name, size=20, color="#2b3a4a"):
    """
    Renderiza un icono como PIL.Image (RGBA) centrado en un lienzo cuadrado.

    Devuelve None si la tipografía no está disponible o el nombre no existe.
    """
    path = font_path()
    if not path or name not in ICONS:
        return None
    try:
        font = ImageFont.truetype(path, int(size * 0.72))
    except OSError:
        return None

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    char = chr(ICONS[name])

    # Medir el glifo para centrarlo exactamente.
    bbox = draw.textbbox((0, 0), char, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1]

    rgb = _hex_to_rgb(color)
    draw.text((x, y), char, font=font, fill=(*rgb, 255))
    return img


def photo(root, name, size=20, color="#2b3a4a"):
    """
    Devuelve un ImageTk.PhotoImage listo para usar en Tkinter.

    Requiere que ya exista una instancia raíz de Tk. Devuelve None si no se
    pudo generar el icono.
    """
    img = render(name, size, color)
    if img is None:
        return None
    return ImageTk.PhotoImage(img)

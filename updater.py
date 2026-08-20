"""
updater.py
==========

Auto-actualización a partir de las releases de GitHub.

Consulta el endpoint https://api.github.com/repos/<repo>/releases/latest,
compara el tag con la versión actual y devuelve la información de la nueva
versión (si la hay).

No descarga ni instala nada: solo avisa para que el usuario descargue el
instalador desde la página del release.
"""

import json
from urllib import request as urlrequest

import config


def _version_tuple(version):
    """Convierte '1.2.3' en (1, 2, 3)."""
    parts = []
    for part in version.lstrip("vV").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _fetch_latest(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urlrequest.Request(url, headers={"User-Agent": "PhoneCam-Updater"})
    with urlrequest.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_update():
    """
    Devuelve una tupla (hay_actualizacion, version_nueva, url, notas) o
    (False, "", "", "") si no hay nada o no se pudo consultar.
    """
    try:
        release = _fetch_latest(config.GITHUB_REPO)
        latest = release.get("tag_name", "").lstrip("vV")
        has_update = _version_tuple(latest) > _version_tuple(config.APP_VERSION)
        return (has_update, latest, release.get("html_url", ""),
                release.get("body", ""))
    except Exception:
        return (False, "", "", "")

"""Muestra de Control de Rondas: seguridad de la app (clave secreta, CSRF, roles, límite de intentos y cabeceras).

Versión casi igual a la real (rondas/seguridad.py). Se usa con Flask.
"""
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import abort, g, redirect, request, session, url_for


def clave_secreta(carpeta: Path) -> str:
    """Usa SECRET_KEY del entorno o genera una y la guarda (solo lectura para el dueño)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    archivo = carpeta / "secret_key"
    if archivo.exists():
        return archivo.read_text().strip()
    clave = secrets.token_hex(32)
    archivo.write_text(clave)
    try:
        archivo.chmod(0o600)
    except OSError:
        pass
    return clave


# ---------- CSRF ----------
def token_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def verificar_csrf():
    enviado = request.form.get("csrf", "")
    if not enviado or not hmac.compare_digest(enviado, session.get("csrf", "")):
        abort(400, "El formulario expiró. Vuelve atrás, recarga la página e inténtalo de nuevo.")


# ---------- supervisor ----------
def requiere_admin(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", siguiente=request.path))
        return vista(*args, **kwargs)
    return envoltura


def requiere_jefe(vista):
    """Cuentas, zonas y ajustes del sitio: solo jefes (g.rol lo carga app.cargar_cuenta)."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", siguiente=request.path))
        if g.get("rol") != "jefe":
            abort(403, "Esta sección es solo para jefes.")
        return vista(*args, **kwargs)
    return envoltura


# ---------- límite de intentos fallidos (PIN y contraseña) ----------
class Limitador:
    def __init__(self, maximo, ventana_seg):
        self.maximo = maximo
        self.ventana = ventana_seg
        self.fallos = defaultdict(deque)

    def _limpiar(self, clave):
        cola = self.fallos[clave]
        corte = time.monotonic() - self.ventana
        while cola and cola[0] < corte:
            cola.popleft()
        return cola

    def bloqueado(self, clave):
        return len(self._limpiar(clave)) >= self.maximo

    def fallo(self, clave):
        self._limpiar(clave).append(time.monotonic())

    def limpiar(self, clave):
        self.fallos.pop(clave, None)


def ip_cliente():
    # Detrás de un proxy (el hosting) la IP real viene en X-Forwarded-For,
    # que app.py resuelve con ProxyFix si DETRAS_DE_PROXY=1.
    return request.remote_addr or "?"


def cabeceras_seguras(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    # Cámara y micrófono solo para esta app (escanear el QR y grabar audios); ubicación, nunca.
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; worker-src 'self'; frame-ancestors 'none'",
    )
    return resp

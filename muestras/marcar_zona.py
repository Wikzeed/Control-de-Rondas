"""
Muestra de Control de Rondas: cómo se marca una zona (extracto simplificado de app.py).

Las reglas que hacen que el registro sea confiable:

- Cada letrero QR apunta a /z/<token>, con un token aleatorio de 16 caracteres (no "Z03"): nadie puede
  marcar una zona sin estar frente al letrero. Si el letrero se pierde o lo fotografían, "Nuevo QR"
  cambia el token y el anterior deja de funcionar.
- La hora la pone el SERVIDOR (en UTC), nunca el celular del guardia.
- El guardia se identifica con su PIN. No se guarda el PIN: se busca por un HMAC del PIN con la clave
  secreta. Con 4 a 6 dígitos ningún hash lo protege de verdad, así que lo que protege es el límite
  de intentos por IP.
- Dos registros iguales (mismo guardia, zona y tipo) en menos de 2 minutos cuentan como uno, y el
  guardia puede anular su propio registro dentro de esos 2 minutos ("me equivoqué").
"""
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

SEG_DUPLICADO = 120
TIPOS = {"inicio": "Inicio de turno", "ronda": "Ronda", "fin": "Fin de turno"}
CLAVE_SECRETA = secrets.token_hex(32)   # en la app real se guarda fuera de git, con permisos 600


def nuevo_token():
    return secrets.token_urlsafe(12)


def clave_pin(pin):
    return hmac.new(CLAVE_SECRETA.encode(), f"pin:{pin}".encode(), "sha256").hexdigest()


def guardia_por_pin(con, pin):
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        return None
    return con.execute("SELECT * FROM guardias WHERE pin_clave = ? AND activo = 1", (clave_pin(pin),)).fetchone()


def registrar(con, token, guardia, tipo):
    """Devuelve (hora, repetido). Lanza ValueError si el QR o el tipo no son válidos."""
    zona = con.execute("SELECT * FROM zonas WHERE token = ? AND activo = 1", (token,)).fetchone()
    if not zona:
        raise ValueError("Este código QR no es válido o la zona fue desactivada. Avise a su supervisor.")
    if tipo not in TIPOS:
        raise ValueError("Acción no válida.")
    ahora = datetime.now(timezone.utc)
    reciente = con.execute(
        "SELECT ts_utc FROM registros WHERE zona_id = ? AND guardia_id = ? AND tipo = ? AND ts_utc >= ? "
        "ORDER BY ts_utc DESC LIMIT 1",
        (zona["id"], guardia["id"], tipo, (ahora - timedelta(seconds=SEG_DUPLICADO)).isoformat()),
    ).fetchone()
    if reciente:
        return datetime.fromisoformat(reciente["ts_utc"]), True
    con.execute("INSERT INTO registros (zona_id, guardia_id, tipo, ts_utc) VALUES (?, ?, ?, ?)",
                (zona["id"], guardia["id"], tipo, ahora.isoformat()))
    con.commit()
    return ahora, False


if __name__ == "__main__":
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE zonas (id INTEGER PRIMARY KEY, codigo TEXT, token TEXT UNIQUE, activo INTEGER DEFAULT 1);
        CREATE TABLE guardias (id INTEGER PRIMARY KEY, nombre TEXT, pin_clave TEXT, activo INTEGER DEFAULT 1);
        CREATE TABLE registros (id INTEGER PRIMARY KEY, zona_id INT, guardia_id INT, tipo TEXT, ts_utc TEXT);
    """)
    token = nuevo_token()
    con.execute("INSERT INTO zonas (codigo, token) VALUES ('Z01', ?)", (token,))
    con.execute("INSERT INTO guardias (nombre, pin_clave) VALUES ('J. Pérez (demo)', ?)", (clave_pin("4829"),))

    guardia = guardia_por_pin(con, "4829")
    print(registrar(con, token, guardia, "ronda"))   # (hora, False): registrado
    print(registrar(con, token, guardia, "ronda"))   # (misma hora, True): repetido, no se duplica
    print(guardia_por_pin(con, "0000"))               # None: PIN equivocado
    try:
        registrar(con, "Z01", guardia, "ronda")       # escribir el código a mano no sirve
    except ValueError as e:
        print(e)

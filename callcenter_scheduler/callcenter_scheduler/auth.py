"""
auth.py
Autenticación simple para el sistema: 2 roles (admin, superadmin).
- Contraseñas con hash PBKDF2-SHA256 + salt (sin dependencias externas de compilación,
  a diferencia de bcrypt, que a veces da problemas al instalar en Windows).
- Sesión firmada con itsdangerous (ya viene con FastAPI/Starlette, no hay que instalar nada
  aparte) guardada en una cookie httpOnly.

Roles:
  - 'admin': operación diaria (Personal, Disponibilidad, Permisos, Horarios, Métricas, Importar).
  - 'superadmin': todo lo anterior + Tarifas + gestión de usuarios.
"""

import hashlib
import os
import secrets

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import db

SECRET_KEY_PATH = os.path.join(os.path.dirname(__file__), ".secret_key")
COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 horas


def _obtener_secret_key() -> str:
    """Genera (una sola vez) y reutiliza una clave secreta local para firmar las sesiones.
    Si el archivo se borra, las sesiones activas se invalidan (hay que volver a loguear)."""
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "r") as f:
            return f.read().strip()
    clave = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(clave)
    return clave


_serializer = URLSafeTimedSerializer(_obtener_secret_key())


def hash_password(password: str, salt: str = None) -> tuple:
    salt = salt or secrets.token_hex(16)
    hash_hex = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return hash_hex, salt


def verificar_password(password: str, password_hash: str, salt: str) -> bool:
    hash_calculado, _ = hash_password(password, salt)
    return secrets.compare_digest(hash_calculado, password_hash)


def crear_sesion_token(user_id: int, username: str, rol: str) -> str:
    return _serializer.dumps({"user_id": user_id, "username": username, "rol": rol})


def leer_sesion_token(token: str):
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def sembrar_usuarios_default(db_path: str = "callcenter.db"):
    """Crea admin/superadmin la primera vez que se inicializa la BD, con contraseñas
    temporales que se DEBEN cambiar en el primer ingreso (debe_cambiar_password=1)."""
    existentes = db.listar_usuarios(db_path=db_path)
    if existentes:
        return None

    creados = []
    for username, rol, password_temporal in [
        ("admin", "admin", "Admin2026*"),
        ("superadmin", "superadmin", "SuperAdmin2026*"),
    ]:
        hash_hex, salt = hash_password(password_temporal)
        db.crear_usuario(username, hash_hex, salt, rol, db_path=db_path)
        creados.append({"username": username, "rol": rol, "password_temporal": password_temporal})
    return creados


# ---------- Protección contra fuerza bruta en el login ----------
# En memoria (no en BD): basta para desalentar ataques automatizados durante una sesión
# del servidor -- un reinicio "perdona" los intentos, lo cual es aceptable para este caso
# de uso (no es un servicio expuesto a internet masivo, es un sistema interno).
import time as _time_module

MAX_INTENTOS_FALLIDOS = 5
VENTANA_BLOQUEO_SEGUNDOS = 15 * 60  # 15 minutos

_intentos_fallidos = {}  # {username: [timestamp1, timestamp2, ...]}


def esta_bloqueado(username: str) -> tuple:
    """Devuelve (bloqueado: bool, segundos_restantes: int)."""
    ahora = _time_module.time()
    intentos = [t for t in _intentos_fallidos.get(username, []) if ahora - t < VENTANA_BLOQUEO_SEGUNDOS]
    _intentos_fallidos[username] = intentos
    if len(intentos) >= MAX_INTENTOS_FALLIDOS:
        segundos_restantes = int(VENTANA_BLOQUEO_SEGUNDOS - (ahora - intentos[0]))
        return True, max(1, segundos_restantes)
    return False, 0


def registrar_intento_fallido(username: str):
    _intentos_fallidos.setdefault(username, []).append(_time_module.time())


def limpiar_intentos_fallidos(username: str):
    _intentos_fallidos.pop(username, None)

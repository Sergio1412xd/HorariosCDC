"""
db.py
Capa de datos del módulo de Personal / Disponibilidad.
Usa SQLite (archivo local, cero configuración). El SQL es estándar,
así que migrar a otra base más adelante (para la versión en línea)
es un cambio mínimo (mismo esquema, mismo tipo de queries).

Modo en línea (Render + Turso): si existen las variables de entorno
TURSO_DATABASE_URL y TURSO_AUTH_TOKEN, get_conn() se conecta a una base
Turso (SQLite en la nube) en vez del archivo local — así los datos
sobreviven a que Render reinicie o "duerma" el servicio (su disco es
efímero). Localmente, sin esas variables, todo funciona exactamente
igual que antes (archivo callcenter.db de siempre).
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

DB_PATH = "callcenter.db"
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
# Caché local del embedded replica de Turso (se regenera solo si Render
# reinicia el disco; los datos reales viven en Turso, no aquí).
_TURSO_CACHE_PATH = "/tmp/turso_cache.db" if os.environ.get("RENDER") else "turso_cache.db"


class _Row:
    """Imita sqlite3.Row (acceso por nombre de columna y dict(fila)) sobre
    las tuplas planas que devuelve el driver 'libsql'."""
    __slots__ = ("_cols", "_vals")

    def __init__(self, columns, values):
        self._cols = columns
        self._vals = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._vals[self._cols.index(key)]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __repr__(self):
        return repr(dict(zip(self._cols, self._vals)))


class _CursorWrapper:
    """Envuelve un cursor de 'libsql' para que .fetchone()/.fetchall() den
    filas tipo _Row (accesibles por nombre, convertibles con dict())."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def _cols(self):
        return [d[0] for d in (self._cursor.description or [])]

    def fetchone(self):
        row = self._cursor.fetchone()
        return None if row is None else _Row(self._cols(), row)

    def fetchall(self):
        cols = self._cols()
        return [_Row(cols, r) for r in self._cursor.fetchall()]


class _TursoConnWrapper:
    """Envuelve la conexión de 'libsql' para que el resto de db.py (que usa
    conn.execute(...).fetchall()/dict(fila), como con sqlite3) no note la
    diferencia."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return _CursorWrapper(cur)

    def executescript(self, script):
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()
        try:
            self._conn.sync()  # empuja los cambios locales a Turso
        except Exception as e:
            print(f"[turso] aviso: no se pudo sincronizar con la nube ({e}); "
                  f"los datos quedaron guardados localmente y se reintentará "
                  f"en la próxima operación.")

    def close(self):
        self._conn.close()

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Valores por defecto pedidos por el negocio (configurables por empleado si aplica)
DEFAULT_HORAS_MIN_SEMANA = 22
DEFAULT_HORAS_MAX_SEMANA = 36
DEFAULT_HORAS_MIN_DIA = 4
DEFAULT_HORAS_MAX_DIA = 8

TIPOS_DISPONIBILIDAD = ("completa", "rango", "no_disponible", "sin_informacion")
TIPOS_PERMISO = ("vacaciones", "capacitacion", "incapacidad", "permiso_remunerado", "permiso_no_remunerado", "otro")


@contextmanager
def get_conn(db_path: str = DB_PATH):
    if TURSO_DATABASE_URL:
        import libsql  # se instala solo si vas a usar Turso (ver requirements.txt)
        raw = libsql.connect(_TURSO_CACHE_PATH, sync_url=TURSO_DATABASE_URL,
                              auth_token=TURSO_AUTH_TOKEN or "")
        try:
            raw.sync()  # trae los datos más recientes de Turso antes de leer/escribir
        except Exception as e:
            print(f"[turso] aviso: no se pudo sincronizar al abrir ({e}); "
                  f"se sigue con la caché local mientras se recupera la conexión.")
        conn = _TursoConnWrapper(raw)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cedula TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            horas_min_dia REAL NOT NULL DEFAULT {DEFAULT_HORAS_MIN_DIA},
            horas_max_dia REAL NOT NULL DEFAULT {DEFAULT_HORAS_MAX_DIA},
            horas_min_semana REAL NOT NULL DEFAULT {DEFAULT_HORAS_MIN_SEMANA},
            horas_max_semana REAL NOT NULL DEFAULT {DEFAULT_HORAS_MAX_SEMANA},
            permite_horas_extra INTEGER NOT NULL DEFAULT 0,
            max_horas_extra_semana REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS disponibilidad (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            dia_semana TEXT NOT NULL,
            tipo TEXT NOT NULL,          -- completa | rango | no_disponible | sin_informacion
            hora_inicio TEXT,            -- 'HH:MM' si tipo = rango
            hora_fin TEXT,               -- 'HH:MM' si tipo = rango
            UNIQUE(empleado_id, dia_semana)
        );

        CREATE TABLE IF NOT EXISTS permisos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,          -- vacaciones | capacitacion | incapacidad | ...
            fecha_inicio TEXT NOT NULL,  -- 'YYYY-MM-DD'
            fecha_fin TEXT NOT NULL,     -- 'YYYY-MM-DD'
            comentario TEXT
        );

        CREATE TABLE IF NOT EXISTS llamadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT,
            campana TEXT NOT NULL,
            fecha TEXT NOT NULL,          -- 'YYYY-MM-DD'
            hora TEXT NOT NULL,           -- 'HH:MM:SS'
            espera_seg REAL,
            duracion_seg REAL,
            agente TEXT,
            resultado TEXT NOT NULL,      -- 'Contestada' | 'Abandonada'
            hash_unico TEXT NOT NULL UNIQUE   -- evita duplicar la misma llamada si se recarga el archivo
        );
        CREATE INDEX IF NOT EXISTS idx_llamadas_fecha ON llamadas(fecha);

        CREATE TABLE IF NOT EXISTS tarifas (
            id INTEGER PRIMARY KEY CHECK (id = 1),   -- fila única, se actualiza siempre
            valor_hora_normal REAL NOT NULL,
            valor_recargo_dominical REAL NOT NULL,   -- tarifa hora trabajada en domingo
            valor_recargo_nocturno REAL NOT NULL,    -- adicional por hora desde las 19:00
            valor_subsidio_transporte_hora REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS historial_turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            fecha TEXT NOT NULL,          -- 'YYYY-MM-DD'
            dia_semana TEXT NOT NULL,
            hora_inicio INTEGER,
            hora_fin INTEGER,
            UNIQUE(empleado_id, fecha)     -- al regenerar la misma semana, se actualiza en vez de duplicar
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            rol TEXT NOT NULL CHECK (rol IN ('admin', 'superadmin')),
            activo INTEGER NOT NULL DEFAULT 1,
            debe_cambiar_password INTEGER NOT NULL DEFAULT 1,
            modulos_permitidos TEXT,
            foto_perfil TEXT,
            nombre_display TEXT
        );

        CREATE TABLE IF NOT EXISTS plantillas_turno (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            hora_inicio INTEGER NOT NULL,
            hora_fin INTEGER NOT NULL,
            dias_aplica TEXT NOT NULL,   -- JSON: ["Lunes","Martes",...]
            duracion_almuerzo_horas REAL NOT NULL DEFAULT 0,  -- ej. 1 = 1h de almuerzo sin pagar
            activo INTEGER NOT NULL DEFAULT 1,
            es_recomendada INTEGER NOT NULL DEFAULT 0  -- 1 = generada por "Recomendar plantillas"
        );

        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,     -- ISO datetime UTC
            username TEXT NOT NULL,
            accion TEXT NOT NULL,         -- ej. 'login', 'crear_usuario', 'cambiar_tarifas', 'generar_horario'
            detalle TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_hora);

        CREATE TABLE IF NOT EXISTS horarios_generados (
            fecha_lunes TEXT PRIMARY KEY,   -- 'YYYY-MM-DD', una fila por semana (la más reciente la reemplaza)
            generado_en TEXT NOT NULL,      -- ISO datetime UTC
            generado_por TEXT NOT NULL,
            parametros TEXT NOT NULL,       -- JSON con los parámetros usados (meta de servicio, shrinkage, etc.)
            resultado TEXT NOT NULL         -- JSON: la respuesta completa (horario, costo, nivel_servicio, cumplimiento)
        );

        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS autorizaciones_horas_extra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            fecha_hora TEXT NOT NULL,
            solicitado_por TEXT NOT NULL,       -- quién hizo el cambio en la pantalla
            autorizado_por TEXT NOT NULL,       -- superadmin cuyas credenciales se confirmaron
            permite_antes INTEGER NOT NULL,
            permite_despues INTEGER NOT NULL,
            horas_extra_antes REAL NOT NULL,
            horas_extra_despues REAL NOT NULL
        );
        """)

        conn.executemany(
            "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)",
            [
                ("horario_operativo_inicio", "11"),
                ("horario_operativo_fin", "23"),
                ("domingo_max_horas", "7"),
                ("max_turnos_por_dia", "1"),
                ("duracion_preferida_max", "6"),
                ("n_dias_prioridad_maxima", "3"),
                ("factor_decaimiento", "0.7"),
                ("max_dias_consecutivos", "6"),
                ("descanso_minimo_horas", "10"),
                ("target_service_level_default", "0.95"),
                ("shrinkage_default", "0.10"),
                ("max_occupancy_default", "0.85"),
                ("target_answer_seconds", "20"),
                ("hora_inicio_recargo_nocturno", "19"),
                ("session_max_age_horas", "12"),
                ("horas_min_dia_default", str(DEFAULT_HORAS_MIN_DIA)),
                ("horas_max_dia_default", str(DEFAULT_HORAS_MAX_DIA)),
                ("horas_min_semana_default", str(DEFAULT_HORAS_MIN_SEMANA)),
                ("horas_max_semana_default", str(DEFAULT_HORAS_MAX_SEMANA)),
                ("semanas_rotacion_historial", "10"),
                ("margen_seguridad_agentes", "0"),
                ("fraccion_piso_minimo", "0.50"),
                ("almuerzo_valle_inicio", "14.5"),
                ("almuerzo_valle_fin", "18.0"),
                ("permitir_descanso_domingo", "false"),
            ],
        )
        conn.execute("""
            INSERT OR IGNORE INTO tarifas (id, valor_hora_normal, valor_recargo_dominical,
                                            valor_recargo_nocturno, valor_subsidio_transporte_hora)
            VALUES (1, 9285, 14326, 2786, 8303)
        """)

        # Migración: si la BD ya existía de antes (sin la columna cedula), se agrega ahora.
        columnas = [r["name"] for r in conn.execute("PRAGMA table_info(empleados)").fetchall()]
        if "cedula" not in columnas:
            conn.execute("ALTER TABLE empleados ADD COLUMN cedula TEXT")
        if "tipo_contrato" not in columnas:
            conn.execute("ALTER TABLE empleados ADD COLUMN tipo_contrato TEXT NOT NULL DEFAULT 'full_time'")
        if "permite_horas_extra" not in columnas:
            conn.execute("ALTER TABLE empleados ADD COLUMN permite_horas_extra INTEGER NOT NULL DEFAULT 0")
        if "max_horas_extra_semana" not in columnas:
            conn.execute("ALTER TABLE empleados ADD COLUMN max_horas_extra_semana REAL NOT NULL DEFAULT 0")

        columnas_usuarios = [r["name"] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
        if columnas_usuarios and "modulos_permitidos" not in columnas_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN modulos_permitidos TEXT")
        if columnas_usuarios and "foto_perfil" not in columnas_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT")
        if columnas_usuarios and "nombre_display" not in columnas_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN nombre_display TEXT")

        columnas_plantilla = [r["name"] for r in conn.execute("PRAGMA table_info(plantillas_turno)").fetchall()]
        if columnas_plantilla and "duracion_almuerzo_horas" not in columnas_plantilla:
            conn.execute("ALTER TABLE plantillas_turno ADD COLUMN duracion_almuerzo_horas REAL NOT NULL DEFAULT 0")
        if columnas_plantilla and "es_recomendada" not in columnas_plantilla:
            conn.execute("ALTER TABLE plantillas_turno ADD COLUMN es_recomendada INTEGER NOT NULL DEFAULT 0")


# ---------- CRUD: Empleados ----------

def crear_empleado(nombre, cedula=None, tipo_contrato="full_time", horas_min_dia=DEFAULT_HORAS_MIN_DIA,
                    horas_max_dia=DEFAULT_HORAS_MAX_DIA, horas_min_semana=DEFAULT_HORAS_MIN_SEMANA,
                    horas_max_semana=DEFAULT_HORAS_MAX_SEMANA, db_path: str = DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO empleados (nombre, cedula, tipo_contrato, horas_min_dia, horas_max_dia, horas_min_semana, horas_max_semana) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nombre, cedula, tipo_contrato, horas_min_dia, horas_max_dia, horas_min_semana, horas_max_semana),
        )
        return cur.lastrowid


def listar_empleados(solo_activos: bool = True, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        q = "SELECT * FROM empleados"
        if solo_activos:
            q += " WHERE activo = 1"
        return [dict(r) for r in conn.execute(q).fetchall()]


def obtener_empleado(empleado_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM empleados WHERE id = ?", (empleado_id,)).fetchone()
        return dict(r) if r else None


def actualizar_empleado(empleado_id: int, db_path: str = DB_PATH, **campos):
    if not campos:
        return
    sets = ", ".join(f"{k} = ?" for k in campos)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE empleados SET {sets} WHERE id = ?", (*campos.values(), empleado_id))


def eliminar_empleado(empleado_id: int, db_path: str = DB_PATH, definitivo: bool = False):
    """Por defecto hace 'soft delete' (activo=0) para no perder historial de horarios pasados."""
    with get_conn(db_path) as conn:
        if definitivo:
            conn.execute("DELETE FROM empleados WHERE id = ?", (empleado_id,))
        else:
            conn.execute("UPDATE empleados SET activo = 0 WHERE id = ?", (empleado_id,))


# ---------- CRUD: Disponibilidad ----------

def set_disponibilidad(empleado_id: int, dia_semana: str, tipo: str,
                        hora_inicio: Optional[str] = None, hora_fin: Optional[str] = None,
                        db_path: str = DB_PATH):
    assert dia_semana in DIAS_SEMANA, f"Día inválido: {dia_semana}"
    assert tipo in TIPOS_DISPONIBILIDAD, f"Tipo inválido: {tipo}"
    if tipo == "rango":
        assert hora_inicio and hora_fin, "Un rango necesita hora_inicio y hora_fin"

    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO disponibilidad (empleado_id, dia_semana, tipo, hora_inicio, hora_fin)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(empleado_id, dia_semana) DO UPDATE SET
                tipo = excluded.tipo, hora_inicio = excluded.hora_inicio, hora_fin = excluded.hora_fin
        """, (empleado_id, dia_semana, tipo, hora_inicio, hora_fin))


def obtener_disponibilidad(empleado_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM disponibilidad WHERE empleado_id = ?", (empleado_id,)
        ).fetchall()
        return {r["dia_semana"]: dict(r) for r in rows}


# ---------- CRUD: Permisos (vacaciones, capacitación, etc.) ----------

def crear_permiso(empleado_id: int, tipo: str, fecha_inicio: str, fecha_fin: str,
                   comentario: str = "", db_path: str = DB_PATH, forzar: bool = False) -> int:
    assert tipo in TIPOS_PERMISO, f"Tipo de permiso inválido: {tipo}"
    if fecha_fin < fecha_inicio:
        raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")

    if not forzar:
        solapados = permisos_solapados(empleado_id, fecha_inicio, fecha_fin, db_path=db_path)
        if solapados:
            raise ValueError(
                f"Ya existe un permiso que se solapa en esas fechas: {solapados}. "
                f"Usa forzar=True si de verdad quieres crearlo igual (ej. permisos parciales del mismo día)."
            )

    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO permisos (empleado_id, tipo, fecha_inicio, fecha_fin, comentario) VALUES (?, ?, ?, ?, ?)",
            (empleado_id, tipo, fecha_inicio, fecha_fin, comentario),
        )
        return cur.lastrowid


def permisos_solapados(empleado_id: int, fecha_inicio: str, fecha_fin: str, db_path: str = DB_PATH):
    """Devuelve los permisos existentes de ese empleado cuyo rango de fechas se cruza con el nuevo."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM permisos
               WHERE empleado_id = ?
                 AND fecha_inicio <= ? AND fecha_fin >= ?""",
            (empleado_id, fecha_fin, fecha_inicio),
        ).fetchall()
        return [dict(r) for r in rows]


def listar_permisos(empleado_id: Optional[int] = None, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        if empleado_id:
            rows = conn.execute("SELECT * FROM permisos WHERE empleado_id = ?", (empleado_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM permisos").fetchall()
        return [dict(r) for r in rows]


def eliminar_permiso(permiso_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM permisos WHERE id = ?", (permiso_id,))


def empleados_de_permiso_en_fecha(fecha: str, db_path: str = DB_PATH):
    """fecha en formato 'YYYY-MM-DD'. Devuelve empleados con permiso activo ese día (para excluirlos del horario)."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT p.*, e.nombre FROM permisos p
               JOIN empleados e ON e.id = p.empleado_id
               WHERE p.fecha_inicio <= ? AND p.fecha_fin >= ?""",
            (fecha, fecha),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- Llamadas (histórico, carga incremental) ----------

def insertar_llamadas_bulk(filas: list[dict], db_path: str = DB_PATH) -> dict:
    """
    Inserta llamadas en bloque. Cada fila debe traer 'hash_unico' ya calculado.
    Usa INSERT OR IGNORE: si la llamada ya existía (mismo hash), la salta sin error.
    Devuelve cuántas se insertaron realmente vs cuántas ya existían.
    """
    with get_conn(db_path) as conn:
        antes = conn.execute("SELECT COUNT(*) c FROM llamadas").fetchone()["c"]
        conn.executemany("""
            INSERT OR IGNORE INTO llamadas
                (numero, campana, fecha, hora, espera_seg, duracion_seg, agente, resultado, hash_unico)
            VALUES (:numero, :campana, :fecha, :hora, :espera_seg, :duracion_seg, :agente, :resultado, :hash_unico)
        """, filas)
        despues = conn.execute("SELECT COUNT(*) c FROM llamadas").fetchone()["c"]
    return {"insertadas_nuevas": despues - antes, "ya_existian": len(filas) - (despues - antes)}


def rango_fechas_llamadas(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT MIN(fecha) mn, MAX(fecha) mx, COUNT(*) c FROM llamadas").fetchone()
        return dict(r)


def obtener_llamadas_df(db_path: str = DB_PATH):
    """Devuelve TODAS las llamadas históricas como lista de dicts (para pasar a pandas)."""
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM llamadas").fetchall()
        return [dict(r) for r in rows]


def eliminar_todas_las_llamadas(db_path: str = DB_PATH) -> int:
    """Borra TODO el histórico de llamadas (para volver a cargar datos limpios desde cero).
    Devuelve cuántas filas se borraron."""
    with get_conn(db_path) as conn:
        antes = conn.execute("SELECT COUNT(*) c FROM llamadas").fetchone()["c"]
        conn.execute("DELETE FROM llamadas")
        return antes


def eliminar_llamadas_rango(fecha_inicio: str, fecha_fin: str, db_path: str = DB_PATH) -> int:
    """Borra solo las llamadas dentro de un rango de fechas (por si el error de datos fue
    solo en un período puntual y no hace falta borrar todo el histórico)."""
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM llamadas WHERE fecha >= ? AND fecha <= ?", (fecha_inicio, fecha_fin))
        return cur.rowcount


# ---------- Tarifas (configurable desde la plataforma) ----------

def obtener_tarifas(db_path: str = DB_PATH) -> dict:
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM tarifas WHERE id = 1").fetchone()
        return dict(r)


def actualizar_tarifas(db_path: str = DB_PATH, **campos):
    if not campos:
        return
    sets = ", ".join(f"{k} = ?" for k in campos)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE tarifas SET {sets} WHERE id = 1", (*campos.values(),))
    return obtener_tarifas(db_path=db_path)


# ---------- Historial de turnos (para rotación justa) ----------

def guardar_turno_historial(empleado_id: int, fecha: str, dia_semana: str,
                             hora_inicio: int = None, hora_fin: int = None, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO historial_turnos (empleado_id, fecha, dia_semana, hora_inicio, hora_fin)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(empleado_id, fecha) DO UPDATE SET
                dia_semana = excluded.dia_semana, hora_inicio = excluded.hora_inicio, hora_fin = excluded.hora_fin
        """, (empleado_id, fecha, dia_semana, hora_inicio, hora_fin))


def guardar_turnos_historial_batch(entradas: list, db_path: str = DB_PATH):
    """Igual que guardar_turno_historial pero para VARIAS filas en una sola transacción --
    generar un horario completo puede necesitar hasta ~120 escrituras (empleados x días);
    hacerlas una por una (una conexión + commit cada vez) es el cuello de botella real de
    rendimiento del generador. 'entradas': lista de tuplas
    (empleado_id, fecha, dia_semana, hora_inicio, hora_fin)."""
    if not entradas:
        return
    with get_conn(db_path) as conn:
        conn.executemany("""
            INSERT INTO historial_turnos (empleado_id, fecha, dia_semana, hora_inicio, hora_fin)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(empleado_id, fecha) DO UPDATE SET
                dia_semana = excluded.dia_semana, hora_inicio = excluded.hora_inicio, hora_fin = excluded.hora_fin
        """, entradas)


def conteo_historico_por_dia_semana(dia_semana: str, fecha_antes_de: str, semanas_atras: int = 10,
                                     db_path: str = DB_PATH) -> dict:
    """
    Cuenta, para cada empleado, cuántas veces trabajó ese día de la semana (ej. 'Domingo')
    en las últimas N semanas ANTES de fecha_antes_de (no cuenta la semana que se está
    generando). Usado para rotar de forma justa: quien menos lo ha trabajado, prioridad.
    """
    from datetime import date as _date, timedelta as _timedelta
    fecha_limite = (_date.fromisoformat(fecha_antes_de) - _timedelta(weeks=semanas_atras)).isoformat()
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT empleado_id, COUNT(*) as c FROM historial_turnos
            WHERE dia_semana = ? AND fecha >= ? AND fecha < ? AND hora_inicio IS NOT NULL
            GROUP BY empleado_id
        """, (dia_semana, fecha_limite, fecha_antes_de)).fetchall()
        return {r["empleado_id"]: r["c"] for r in rows}


# ---------- Usuarios (autenticación) ----------

MODULOS_DISPONIBLES = [
    "importar", "personal", "disponibilidad", "permisos", "metricas",
    "turnos", "horarios", "historial", "comparar", "brecha",
]  # Tarifas/Usuarios/Auditoría/Configuración quedan siempre exclusivos de superadmin,
   # sin importar lo que se marque aquí -- no forman parte de esta lista a propósito.


def crear_usuario(username: str, password_hash: str, salt: str, rol: str,
                   debe_cambiar_password: bool = True, modulos_permitidos: list = None,
                   db_path: str = DB_PATH) -> int:
    modulos_json = json.dumps(modulos_permitidos, ensure_ascii=False) if modulos_permitidos is not None else None
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (username, password_hash, salt, rol, debe_cambiar_password, modulos_permitidos) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, salt, rol, int(debe_cambiar_password), modulos_json),
        )
        return cur.lastrowid


def obtener_usuario_por_username(username: str, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["modulos_permitidos"] = json.loads(d["modulos_permitidos"]) if d["modulos_permitidos"] else None
        return d


def obtener_usuario(user_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["modulos_permitidos"] = json.loads(d["modulos_permitidos"]) if d["modulos_permitidos"] else None
        return d


def listar_usuarios(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT id, username, rol, activo, debe_cambiar_password, modulos_permitidos FROM usuarios").fetchall()
        resultado = []
        for r in rows:
            d = dict(r)
            d["modulos_permitidos"] = json.loads(d["modulos_permitidos"]) if d["modulos_permitidos"] else None
            resultado.append(d)
        return resultado


# ---------- Horas extra (requieren autorización de superadmin) ----------

def registrar_autorizacion_horas_extra(empleado_id: int, solicitado_por: str, autorizado_por: str,
                                        permite_antes: bool, permite_despues: bool,
                                        horas_extra_antes: float, horas_extra_despues: float,
                                        db_path: str = DB_PATH):
    from datetime import datetime, timezone
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO autorizaciones_horas_extra
                (empleado_id, fecha_hora, solicitado_por, autorizado_por, permite_antes, permite_despues,
                 horas_extra_antes, horas_extra_despues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (empleado_id, datetime.now(timezone.utc).isoformat(), solicitado_por, autorizado_por,
              int(permite_antes), int(permite_despues), horas_extra_antes, horas_extra_despues))
        conn.execute(
            "UPDATE empleados SET permite_horas_extra = ?, max_horas_extra_semana = ? WHERE id = ?",
            (int(permite_despues), horas_extra_despues if permite_despues else 0, empleado_id),
        )


def listar_autorizaciones_horas_extra(db_path: str = DB_PATH, limite: int = 200) -> list:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT a.*, e.nombre AS empleado_nombre FROM autorizaciones_horas_extra a
            JOIN empleados e ON e.id = a.empleado_id
            ORDER BY a.fecha_hora DESC LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]


def actualizar_perfil_usuario(user_id: int, foto_perfil: str = None, nombre_display: str = None,
                               db_path: str = DB_PATH):
    """foto_perfil: string base64 (data URL) de una imagen pequeña, o None para quitarla.
    nombre_display: cómo saludar a la persona (ej. 'Sergio' en vez de su username), o None
    para usar el username tal cual."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE usuarios SET foto_perfil = ?, nombre_display = ? WHERE id = ?",
            (foto_perfil, nombre_display, user_id),
        )


def actualizar_password_usuario(user_id: int, password_hash: str, salt: str, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE usuarios SET password_hash = ?, salt = ?, debe_cambiar_password = 0 WHERE id = ?",
            (password_hash, salt, user_id),
        )


def actualizar_usuario(user_id: int, db_path: str = DB_PATH, **campos):
    if not campos:
        return
    if "modulos_permitidos" in campos and isinstance(campos["modulos_permitidos"], list):
        campos["modulos_permitidos"] = json.dumps(campos["modulos_permitidos"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in campos)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE usuarios SET {sets} WHERE id = ?", (*campos.values(), user_id))


def eliminar_usuario(user_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (user_id,))


def eliminar_usuario_definitivo(user_id: int, db_path: str = DB_PATH):
    """Borra la cuenta por completo (no solo desactivarla) -- el historial de auditoría
    guarda el username como texto plano, no una referencia al id, así que no se pierde
    ningún registro de lo que esa persona hizo antes de borrar su cuenta."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))


# ---------- Plantillas de turno (horarios válidos predefinidos) ----------

def crear_plantilla_turno(hora_inicio: int, hora_fin: int, dias_aplica: list, nombre: str = None,
                           duracion_almuerzo_horas: float = 0, es_recomendada: bool = False,
                           db_path: str = DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO plantillas_turno (nombre, hora_inicio, hora_fin, dias_aplica, duracion_almuerzo_horas, es_recomendada) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, hora_inicio, hora_fin, json.dumps(dias_aplica, ensure_ascii=False), duracion_almuerzo_horas, es_recomendada),
        )
        return cur.lastrowid


def listar_plantillas_turno(solo_activas: bool = True, db_path: str = DB_PATH) -> list:
    with get_conn(db_path) as conn:
        q = "SELECT * FROM plantillas_turno"
        if solo_activas:
            q += " WHERE activo = 1"
        q += " ORDER BY hora_inicio"
        filas = [dict(r) for r in conn.execute(q).fetchall()]
        for f in filas:
            f["dias_aplica"] = json.loads(f["dias_aplica"])
        return filas


def obtener_plantilla_turno(plantilla_id: int, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM plantillas_turno WHERE id = ?", (plantilla_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["dias_aplica"] = json.loads(d["dias_aplica"])
        return d


def actualizar_plantilla_turno(plantilla_id: int, db_path: str = DB_PATH, **campos):
    if not campos:
        return
    if "dias_aplica" in campos:
        campos["dias_aplica"] = json.dumps(campos["dias_aplica"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in campos)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE plantillas_turno SET {sets} WHERE id = ?", (*campos.values(), plantilla_id))


def eliminar_plantilla_turno(plantilla_id: int, db_path: str = DB_PATH, definitivo: bool = True):
    with get_conn(db_path) as conn:
        if definitivo:
            conn.execute("DELETE FROM plantillas_turno WHERE id = ?", (plantilla_id,))
        else:
            conn.execute("UPDATE plantillas_turno SET activo = 0 WHERE id = ?", (plantilla_id,))


# ---------- Auditoría ----------

def _plantillas_turno_default() -> list:
    """Lista canónica de las 13 plantillas de turno del negocio (con sus horas de almuerzo).
    Función única de la que dependen tanto la siembra automática como la restauración
    manual, para que nunca queden desincronizadas entre sí."""
    DOM_A_JUE = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves"]
    LUN_A_SAB = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    TODOS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

    return [
        (17, 21, DOM_A_JUE, "Domingo a jueves 17-21h", 0),
        (18, 22, ["Viernes", "Sábado"], "Vie-Sáb 18-22h", 0),
        (11, 15, LUN_A_SAB, "Lunes a sábado 11-15h", 0),
        (11, 17, TODOS, "Lunes a domingo 11-17h", 0),
        (11, 16, ["Sábado", "Jueves", "Viernes"], "Sáb-Jue-Vie 11-16h", 0),
        (12, 21, ["Martes", "Viernes", "Jueves"], "Mar-Vie-Jue 12-21h (con almuerzo)", 1),
        (11, 20, ["Viernes", "Sábado"], "Vie-Sáb 11-20h (con almuerzo)", 1),
        (12, 18, ["Sábado", "Domingo"], "Sáb-Dom 12-18h", 0),
        (12, 20, ["Sábado"], "Sábado 12-20h (con almuerzo)", 1),
        (13, 21, ["Domingo", "Martes"], "Dom-Mar 13-21h", 0),
        (13, 22, ["Viernes", "Sábado"], "Vie-Sáb 13-22h", 0),
        (14, 21, ["Domingo"], "Domingo 14-21h", 0),
        (14, 22, ["Viernes", "Sábado"], "Vie-Sáb 14-22h (con almuerzo)", 1),
    ]


def sembrar_plantillas_turno_default(db_path: str = DB_PATH):
    """Crea las plantillas de turno estándar del negocio la primera vez que se usa el
    sistema (tabla vacía). Si ya hay alguna plantilla (creada antes, o dejada por el
    usuario), no hace nada -- para forzar el set actual sin importar lo que haya, usa
    restaurar_plantillas_turno_default() en su lugar."""
    if listar_plantillas_turno(solo_activas=False, db_path=db_path):
        return None

    plantillas_default = _plantillas_turno_default()
    for hi, hf, dias, nombre, almuerzo in plantillas_default:
        crear_plantilla_turno(hi, hf, dias, nombre=nombre, duracion_almuerzo_horas=almuerzo, db_path=db_path)
    return len(plantillas_default)


def restaurar_plantillas_turno_default(db_path: str = DB_PATH) -> int:
    """Borra TODAS las plantillas actuales (sin importar cuáles sean) y deja únicamente
    el set estándar del negocio. Acción explícita del usuario -- a diferencia de la
    siembra automática, esta SÍ sobreescribe lo que hubiera antes."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM plantillas_turno")

    plantillas_default = _plantillas_turno_default()
    for hi, hf, dias, nombre, almuerzo in plantillas_default:
        crear_plantilla_turno(hi, hf, dias, nombre=nombre, duracion_almuerzo_horas=almuerzo, db_path=db_path)
    return len(plantillas_default)


def registrar_auditoria(username: str, accion: str, detalle: str = "", db_path: str = DB_PATH):
    from datetime import datetime, timezone
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO auditoria (fecha_hora, username, accion, detalle) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), username, accion, detalle),
        )


def listar_auditoria(limite: int = 200, db_path: str = DB_PATH, accion: str = None,
                      usuario: str = None, fecha_inicio: str = None, fecha_fin: str = None,
                      busqueda: str = None) -> list:
    query = "SELECT * FROM auditoria WHERE 1=1"
    params = []
    if accion:
        query += " AND accion = ?"
        params.append(accion)
    if usuario:
        query += " AND username = ?"
        params.append(usuario)
    if fecha_inicio:
        query += " AND fecha_hora >= ?"
        params.append(fecha_inicio)
    if fecha_fin:
        query += " AND fecha_hora <= ?"
        params.append(fecha_fin + "T23:59:59")
    if busqueda:
        like = f"%{busqueda}%"
        query += " AND (detalle LIKE ? OR accion LIKE ? OR username LIKE ?)"
        params.extend([like, like, like])
    query += " ORDER BY fecha_hora DESC LIMIT ?"
    params.append(limite)
    with get_conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def listar_acciones_auditoria(db_path: str = DB_PATH) -> list:
    """Tipos de evento distintos que ya existen en el log -- para llenar el filtro sin
    tener que hardcodear la lista (nuevos tipos de evento aparecen solos)."""
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT accion FROM auditoria ORDER BY accion").fetchall()
        return [r["accion"] for r in rows]


def listar_usuarios_auditoria(db_path: str = DB_PATH) -> list:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT username FROM auditoria ORDER BY username").fetchall()
        return [r["username"] for r in rows]


# ---------- Historial de horarios generados ----------

def guardar_horario_generado(fecha_lunes: str, generado_por: str, parametros: dict, resultado: dict,
                              db_path: str = DB_PATH):
    from datetime import datetime, timezone
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO horarios_generados (fecha_lunes, generado_en, generado_por, parametros, resultado)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(fecha_lunes) DO UPDATE SET
                generado_en = excluded.generado_en, generado_por = excluded.generado_por,
                parametros = excluded.parametros, resultado = excluded.resultado
        """, (fecha_lunes, datetime.now(timezone.utc).isoformat(), generado_por,
              json.dumps(parametros, ensure_ascii=False), json.dumps(resultado, ensure_ascii=False)))


def listar_horarios_generados(db_path: str = DB_PATH) -> list:
    """Resumen (sin el detalle completo) de cada semana que se haya generado alguna vez,
    más reciente primero -- para la vista de Historial."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT fecha_lunes, generado_en, generado_por, parametros, resultado FROM horarios_generados "
            "ORDER BY fecha_lunes DESC"
        ).fetchall()
        resumen = []
        for r in rows:
            resultado = json.loads(r["resultado"])
            resumen.append({
                "fecha_lunes": r["fecha_lunes"], "generado_en": r["generado_en"], "generado_por": r["generado_por"],
                "sl_estimado_pct": resultado.get("nivel_servicio", {}).get("sl_estimado_semana_pct"),
                "costo_total": resultado.get("costo", {}).get("total_semana"),
                "cumple_normativa": resultado.get("cumplimiento", {}).get("resumen", {}).get("cumple"),
            })
        return resumen


def obtener_horario_generado(fecha_lunes: str, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM horarios_generados WHERE fecha_lunes = ?", (fecha_lunes,)
        ).fetchone()
        if not r:
            return None
        return {
            "fecha_lunes": r["fecha_lunes"], "generado_en": r["generado_en"], "generado_por": r["generado_por"],
            "parametros": json.loads(r["parametros"]), "resultado": json.loads(r["resultado"]),
        }


def eliminar_horario_generado(fecha_lunes: str, db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM horarios_generados WHERE fecha_lunes = ?", (fecha_lunes,))


# ---------- Configuración general (solo superadmin) ----------

def _parse_bool_config(valor) -> bool:
    """bool('false') da True en Python (cualquier string no vacío es 'verdadero') -- este
    parser interpreta el texto real guardado en la BD en vez de caer en esa trampa."""
    return str(valor).strip().lower() in ("true", "1", "si", "sí")


_CONFIG_TIPOS = {
    "horario_operativo_inicio": int, "horario_operativo_fin": int, "domingo_max_horas": int,
    "max_turnos_por_dia": int, "duracion_preferida_max": int, "n_dias_prioridad_maxima": int,
    "factor_decaimiento": float, "max_dias_consecutivos": int, "descanso_minimo_horas": int,
    "target_service_level_default": float, "shrinkage_default": float, "max_occupancy_default": float,
    "target_answer_seconds": int, "hora_inicio_recargo_nocturno": int, "session_max_age_horas": int,
    "horas_min_dia_default": float, "horas_max_dia_default": float,
    "horas_min_semana_default": float, "horas_max_semana_default": float,
    "semanas_rotacion_historial": int,
    "margen_seguridad_agentes": int,
    "fraccion_piso_minimo": float,
    "almuerzo_valle_inicio": float, "almuerzo_valle_fin": float,
    "permitir_descanso_domingo": _parse_bool_config,
}


def obtener_configuracion(db_path: str = DB_PATH) -> dict:
    """Todos los parámetros generales del sistema, con el tipo correcto (int/float) ya
    convertido -- se guardan como texto en la BD pero se devuelven listos para usar."""
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT clave, valor FROM configuracion").fetchall()
    resultado = {}
    for r in rows:
        tipo = _CONFIG_TIPOS.get(r["clave"], str)
        try:
            resultado[r["clave"]] = tipo(r["valor"])
        except (TypeError, ValueError):
            resultado[r["clave"]] = r["valor"]
    return resultado


def obtener_configuracion_valor(clave: str, default=None, db_path: str = DB_PATH):
    return obtener_configuracion(db_path=db_path).get(clave, default)


def actualizar_configuracion(cambios: dict, db_path: str = DB_PATH) -> dict:
    with get_conn(db_path) as conn:
        for clave, valor in cambios.items():
            conn.execute(
                "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, str(valor)),
            )
    return obtener_configuracion(db_path=db_path)

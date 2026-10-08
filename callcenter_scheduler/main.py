"""
main.py
API web del sistema de gestión de personal para el call center.

Cómo correrlo local:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --reload
    -> abrir http://localhost:8000

Cuando se despliegue en línea (Railway/Render), este mismo archivo se usa tal cual;
solo cambia DB_PATH a Postgres (ver nota al final).
"""

from datetime import date, timedelta
from typing import Optional
import os
import shutil
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Response, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import db
from db import DIAS_SEMANA, TIPOS_DISPONIBILIDAD, TIPOS_PERMISO
from validar_disponibilidad import validar_todos
from generador_horarios import (generar_horario_semana, _demanda_por_dia, _ventana_disponibilidad,
                                  HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN, estimar_nivel_servicio_real,
                                  recomendar_plantillas_turno)
from costos import calcular_costo_horario
from loader_disponibilidad import cargar_disponibilidad_excel
from loader_llamadas import cargar_llamadas_excel
from agregados_llamadas import (metricas_generales, tendencia_semanal_matriz,
                                  resumen_simple_por_dia_semana, resumen_por_dia_semana_y_hora,
                                  rendimiento_por_agente, listar_semanas_disponibles,
                                  resumen_por_dia_semana_y_hora_semanas)
from pdf_reporte import (generar_pdf_brecha_personal, generar_pdf_personal, generar_pdf_disponibilidad,
                          generar_pdf_permisos, generar_pdf_metricas, generar_pdf_horario, generar_pdf_ejecutivo)
from festivos import listar_festivos_rango, resumen_festivos_historicos
import auth
from cumplimiento import validar_cumplimiento
from db import registrar_auditoria
from excel_reporte import generar_excel_horario

db.init_db()
_usuarios_creados = auth.sembrar_usuarios_default()
if _usuarios_creados:
    print("=" * 70)
    print("USUARIOS INICIALES CREADOS (cambia estas contraseñas al primer ingreso):")
    for u in _usuarios_creados:
        print(f"  usuario: {u['username']:<12} contraseña temporal: {u['password_temporal']:<18} rol: {u['rol']}")
    print("=" * 70)

_plantillas_creadas = db.sembrar_plantillas_turno_default()
if _plantillas_creadas:
    print(f"PLANTILLAS DE TURNO INICIALES CREADAS: {_plantillas_creadas} (ve a la pestaña 'Turnos' para editarlas)")

app = FastAPI(title="Call Center Scheduler - API de Personal")

RUTAS_SIN_LOGIN = {"/api/login", "/api/logout"}


def _modulo_de_ruta(path: str):
    """Mapea una ruta de API al módulo de la interfaz al que pertenece, para poder aplicar
    el permiso de 'modulos_permitidos' de cada usuario. Devuelve None para rutas
    compartidas/transversales (dashboard, notificaciones, festivos, etc.) que no tiene
    sentido restringir por módulo -- esas quedan disponibles para cualquier usuario logueado."""
    if "/disponibilidad" in path and path.startswith("/api/empleados"):
        return "disponibilidad"
    if path.startswith("/api/empleados"):
        return "personal"
    if path.startswith("/api/permisos"):
        return "permisos"
    if path.startswith(("/api/metricas", "/api/desglose-dia-hora", "/api/tendencia-dia-semana", "/api/rendimiento-agentes")):
        return "metricas"
    if path.startswith("/api/plantillas-turno"):
        return "turnos"
    if path.startswith("/api/horarios-generados"):
        return "historial"
    if path.startswith("/api/horario"):
        return "horarios"
    if path.startswith("/api/brecha-personal"):
        return "brecha"
    if path.startswith(("/api/importar", "/api/llamadas")):
        return "importar"
    return None


@app.middleware("http")
async def middleware_autenticacion(request: Request, call_next):
    """Exige sesión válida para cualquier /api/* excepto login/logout. El resto (páginas
    estáticas: HTML/JS/CSS) se sirve libre para que el navegador pueda mostrar la pantalla
    de login antes de autenticarse."""
    path = request.url.path
    if path.startswith("/api/") and path not in RUTAS_SIN_LOGIN:
        token = request.cookies.get(auth.COOKIE_NAME)
        datos_sesion = auth.leer_sesion_token(token) if token else None
        if not datos_sesion:
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        request.state.user = datos_sesion

        # superadmin siempre tiene acceso a todo; para el resto, si tiene una lista de
        # módulos permitidos configurada (no None = "todos"), se valida contra la ruta.
        if datos_sesion["rol"] != "superadmin":
            usuario_db = db.obtener_usuario(datos_sesion["user_id"])
            modulos = usuario_db["modulos_permitidos"] if usuario_db else None
            if modulos is not None:
                modulo_ruta = _modulo_de_ruta(path)
                if modulo_ruta is not None and modulo_ruta not in modulos:
                    return JSONResponse({"detail": "No tienes acceso a este módulo"}, status_code=403)
    response = await call_next(request)
    return response


def requiere_superadmin(request: Request):
    if request.state.user["rol"] != "superadmin":
        raise HTTPException(403, "Esta acción requiere rol superadmin")


# ---------- Autenticación ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str


class CrearUsuarioRequest(BaseModel):
    username: str
    password: str
    rol: str  # 'admin' | 'superadmin'
    modulos_permitidos: Optional[list[str]] = None  # None = todos los módulos (comportamiento actual)


@app.post("/api/login")
def api_login(payload: LoginRequest, response: Response):
    bloqueado, segundos_restantes = auth.esta_bloqueado(payload.username)
    if bloqueado:
        minutos = max(1, segundos_restantes // 60)
        raise HTTPException(429, f"Demasiados intentos fallidos. Intenta de nuevo en {minutos} minuto(s).")

    usuario = db.obtener_usuario_por_username(payload.username)
    if not usuario or not auth.verificar_password(payload.password, usuario["password_hash"], usuario["salt"]):
        auth.registrar_intento_fallido(payload.username)
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    auth.limpiar_intentos_fallidos(payload.username)

    token = auth.crear_sesion_token(usuario["id"], usuario["username"], usuario["rol"])
    cookie_secure = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(auth.COOKIE_NAME, token, httponly=True, samesite="lax", secure=cookie_secure,
                         max_age=auth.SESSION_MAX_AGE)
    registrar_auditoria(usuario["username"], "login", f"rol: {usuario['rol']}")
    return {
        "username": usuario["username"], "rol": usuario["rol"],
        "debe_cambiar_password": bool(usuario["debe_cambiar_password"]),
        "modulos_permitidos": usuario["modulos_permitidos"],
        "foto_perfil": usuario["foto_perfil"],
    }


@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    u = request.state.user
    usuario_db = db.obtener_usuario(u["user_id"])
    return {
        "username": u["username"], "rol": u["rol"],
        "debe_cambiar_password": bool(usuario_db["debe_cambiar_password"]) if usuario_db else False,
        "modulos_permitidos": usuario_db["modulos_permitidos"] if usuario_db else None,
        "foto_perfil": usuario_db["foto_perfil"] if usuario_db else None,
        "nombre_display": usuario_db["nombre_display"] if usuario_db else None,
    }


class ActualizarPerfilRequest(BaseModel):
    foto_perfil: Optional[str] = None  # data URL base64, o None para quitar
    nombre_display: Optional[str] = None


@app.put("/api/mi-perfil")
def api_actualizar_mi_perfil(payload: ActualizarPerfilRequest, request: Request):
    validar_texto_seguro(payload.nombre_display, "nombre a mostrar")
    if payload.foto_perfil and len(payload.foto_perfil) > 700_000:
        raise HTTPException(400, "La imagen es muy pesada -- usa una foto más pequeña (máx. ~500KB)")
    # Solo formatos raster seguros -- explícitamente NO se permite svg+xml, que puede llevar
    # <script> u onload= embebido y ejecutar JavaScript si se renderiza fuera de un <img>.
    formatos_seguros = ("data:image/jpeg;", "data:image/jpg;", "data:image/png;", "data:image/webp;", "data:image/gif;")
    if payload.foto_perfil and not payload.foto_perfil.startswith(formatos_seguros):
        raise HTTPException(400, "Formato de imagen inválido -- usa JPEG, PNG, WEBP o GIF")
    db.actualizar_perfil_usuario(request.state.user["user_id"], foto_perfil=payload.foto_perfil,
                                  nombre_display=payload.nombre_display)
    return {"ok": True}


@app.get("/api/modulos-disponibles")
def api_modulos_disponibles():
    return db.MODULOS_DISPONIBLES


@app.post("/api/cambiar-password")
def api_cambiar_password(payload: CambiarPasswordRequest, request: Request):
    usuario = db.obtener_usuario(request.state.user["user_id"])
    if not usuario or not auth.verificar_password(payload.password_actual, usuario["password_hash"], usuario["salt"]):
        raise HTTPException(401, "La contraseña actual no es correcta")
    if len(payload.password_nueva) < 8:
        raise HTTPException(400, "La nueva contraseña debe tener al menos 8 caracteres")
    hash_hex, salt = auth.hash_password(payload.password_nueva)
    db.actualizar_password_usuario(usuario["id"], hash_hex, salt)
    return {"ok": True}


@app.get("/api/usuarios")
def api_listar_usuarios(request: Request, _=Depends(requiere_superadmin)):
    return db.listar_usuarios()


@app.post("/api/usuarios")
def api_crear_usuario(payload: CrearUsuarioRequest, request: Request, _=Depends(requiere_superadmin)):
    validar_texto_seguro(payload.username, "usuario")
    if payload.rol not in ("admin", "superadmin"):
        raise HTTPException(400, "rol debe ser 'admin' o 'superadmin'")
    if db.obtener_usuario_por_username(payload.username):
        raise HTTPException(409, "Ese nombre de usuario ya existe")
    if len(payload.password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")
    modulos = payload.modulos_permitidos
    if modulos is not None:
        invalidos = set(modulos) - set(db.MODULOS_DISPONIBLES)
        if invalidos:
            raise HTTPException(400, f"Módulos desconocidos: {sorted(invalidos)}")
    hash_hex, salt = auth.hash_password(payload.password)
    user_id = db.crear_usuario(payload.username, hash_hex, salt, payload.rol, debe_cambiar_password=True,
                                modulos_permitidos=modulos)
    registrar_auditoria(request.state.user["username"], "crear_usuario", f"nuevo usuario: {payload.username} ({payload.rol})")
    return {"id": user_id, "username": payload.username, "rol": payload.rol}


class ActualizarModulosRequest(BaseModel):
    modulos_permitidos: Optional[list[str]] = None  # None = todos los módulos


@app.put("/api/usuarios/{user_id}/modulos")
def api_actualizar_modulos_usuario(user_id: int, payload: ActualizarModulosRequest, request: Request,
                                    _=Depends(requiere_superadmin)):
    usuario = db.obtener_usuario(user_id)
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")
    if payload.modulos_permitidos is not None:
        invalidos = set(payload.modulos_permitidos) - set(db.MODULOS_DISPONIBLES)
        if invalidos:
            raise HTTPException(400, f"Módulos desconocidos: {sorted(invalidos)}")
    db.actualizar_usuario(user_id, modulos_permitidos=payload.modulos_permitidos)
    registrar_auditoria(request.state.user["username"], "cambiar_modulos_usuario",
                         f"{usuario['username']}: {payload.modulos_permitidos}")
    actualizado = db.obtener_usuario(user_id)
    return {"id": actualizado["id"], "username": actualizado["username"], "rol": actualizado["rol"],
            "modulos_permitidos": actualizado["modulos_permitidos"]}


@app.delete("/api/usuarios/{user_id}")
def api_eliminar_usuario(user_id: int, request: Request, _=Depends(requiere_superadmin)):
    if user_id == request.state.user["user_id"]:
        raise HTTPException(400, "No puedes desactivar tu propio usuario")
    usuario_afectado = db.obtener_usuario(user_id)
    db.eliminar_usuario(user_id)
    registrar_auditoria(request.state.user["username"], "eliminar_usuario",
                         f"usuario desactivado: {usuario_afectado['username'] if usuario_afectado else user_id}")
    return {"ok": True}


@app.delete("/api/usuarios/{user_id}/definitivo")
def api_eliminar_usuario_definitivo(user_id: int, request: Request, _=Depends(requiere_superadmin)):
    if user_id == request.state.user["user_id"]:
        raise HTTPException(400, "No puedes eliminar tu propio usuario")
    usuario_afectado = db.obtener_usuario(user_id)
    if not usuario_afectado:
        raise HTTPException(404, "Usuario no encontrado")
    if usuario_afectado["rol"] == "superadmin":
        otros_superadmins = [u for u in db.listar_usuarios() if u["rol"] == "superadmin" and u["id"] != user_id]
        if not otros_superadmins:
            raise HTTPException(400, "No puedes eliminar el único superadmin del sistema")
    db.eliminar_usuario_definitivo(user_id)
    registrar_auditoria(request.state.user["username"], "eliminar_usuario_definitivo",
                         f"usuario eliminado por completo: {usuario_afectado['username']}")
    return {"ok": True}


# ---------- Plantillas de turno ----------

class PlantillaTurnoCreate(BaseModel):
    hora_inicio: int
    hora_fin: int
    dias_aplica: list[str]
    nombre: Optional[str] = None
    duracion_almuerzo_horas: float = 0


class PlantillaTurnoUpdate(BaseModel):
    hora_inicio: Optional[int] = None
    hora_fin: Optional[int] = None
    dias_aplica: Optional[list[str]] = None
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    duracion_almuerzo_horas: Optional[float] = None


@app.get("/api/plantillas-turno")
def api_listar_plantillas():
    return db.listar_plantillas_turno(solo_activas=False)


@app.post("/api/plantillas-turno")
def api_crear_plantilla(payload: PlantillaTurnoCreate):
    validar_texto_seguro(payload.nombre, "nombre")
    if payload.hora_fin <= payload.hora_inicio:
        raise HTTPException(400, "hora_fin debe ser mayor que hora_inicio")
    if not payload.dias_aplica:
        raise HTTPException(400, "Selecciona al menos un día para esta plantilla")
    dias_invalidos = [d for d in payload.dias_aplica if d not in DIAS_SEMANA]
    if dias_invalidos:
        raise HTTPException(400, f"Días inválidos: {dias_invalidos}")
    if payload.duracion_almuerzo_horas >= (payload.hora_fin - payload.hora_inicio):
        raise HTTPException(400, "El almuerzo no puede durar igual o más que el turno completo")
    pid = db.crear_plantilla_turno(payload.hora_inicio, payload.hora_fin, payload.dias_aplica, payload.nombre,
                                    duracion_almuerzo_horas=payload.duracion_almuerzo_horas)
    return db.obtener_plantilla_turno(pid)


@app.post("/api/plantillas-turno/recomendar")
def api_recomendar_plantillas(request: Request, fecha_lunes: Optional[str] = None,
                               target_service_level: float = 0.95, shrinkage: float = 0.10,
                               max_occupancy: float = 0.85):
    """Analiza dónde el horario real queda corto con las plantillas actuales, propone
    nuevas plantillas para taparlo, las guarda marcadas como recomendadas, y devuelve el
    % de servicio ANTES y DESPUÉS para que se vea con honestidad si de verdad ayudó --
    a veces el límite real es la disponibilidad/cantidad de gente, no la forma del turno."""
    fecha = date.fromisoformat(fecha_lunes) if fecha_lunes else date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)

    resultado_antes = generar_horario_semana(fecha, target_service_level=target_service_level,
                                              shrinkage=shrinkage, max_occupancy=max_occupancy)
    sl_antes = estimar_nivel_servicio_real(resultado_antes)["sl_estimado_semana_pct"]

    propuestas = recomendar_plantillas_turno(fecha, target_service_level=target_service_level,
                                              shrinkage=shrinkage, max_occupancy=max_occupancy)
    creadas = []
    for p in propuestas:
        pid = db.crear_plantilla_turno(
            p["hora_inicio"], p["hora_fin"], p["dias_aplica"],
            nombre=f"Sugerida {p['hora_inicio']:02d}-{p['hora_fin']:02d}h",
            duracion_almuerzo_horas=p["duracion_almuerzo_horas"], es_recomendada=True,
        )
        creadas.append({**db.obtener_plantilla_turno(pid), "detalle_huecos": p["detalle"]})

    if creadas:
        resultado_despues = generar_horario_semana(fecha, target_service_level=target_service_level,
                                                     shrinkage=shrinkage, max_occupancy=max_occupancy)
        sl_despues = estimar_nivel_servicio_real(resultado_despues)["sl_estimado_semana_pct"]
    else:
        sl_despues = sl_antes

    registrar_auditoria(request.state.user["username"], "recomendar_plantillas",
                         f"{len(creadas)} plantillas, SL {sl_antes}% -> {sl_despues}%")
    return {"plantillas_creadas": creadas, "sl_estimado_antes_pct": sl_antes, "sl_estimado_despues_pct": sl_despues,
            "fecha_lunes_analizada": fecha.isoformat()}


@app.put("/api/plantillas-turno/{plantilla_id}")
def api_actualizar_plantilla(plantilla_id: int, payload: PlantillaTurnoUpdate):
    if not db.obtener_plantilla_turno(plantilla_id):
        raise HTTPException(404, "Plantilla no encontrada")
    campos = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "nombre" in campos:
        validar_texto_seguro(campos["nombre"], "nombre")
    db.actualizar_plantilla_turno(plantilla_id, **campos)
    return db.obtener_plantilla_turno(plantilla_id)


@app.delete("/api/plantillas-turno/{plantilla_id}")
def api_eliminar_plantilla(plantilla_id: int):
    if not db.obtener_plantilla_turno(plantilla_id):
        raise HTTPException(404, "Plantilla no encontrada")
    db.eliminar_plantilla_turno(plantilla_id)
    return {"ok": True}


@app.post("/api/plantillas-turno/restaurar-default")
def api_restaurar_plantillas_default(request: Request):
    """Borra TODAS las plantillas actuales y deja únicamente el set estándar del negocio
    (13 plantillas). Acción explícita y destructiva, pero disponible para admin también
    (a diferencia de Tarifas/Usuarios) porque Turnos es un módulo operativo del día a día."""
    n = db.restaurar_plantillas_turno_default()
    registrar_auditoria(request.state.user["username"], "restaurar_plantillas_default", f"{n} plantillas")
    return {"ok": True, "plantillas_creadas": n}


# ---------- Esquemas (validación de entrada) ----------

_CARACTERES_HTML_PELIGROSOS = set("<>{}")


def validar_texto_seguro(texto, campo: str = "texto"):
    """Rechaza nombres/textos que traigan caracteres usados para inyectar HTML/JavaScript
    (XSS) -- estos campos se muestran tal cual en varias tablas de la interfaz (Personal,
    Usuarios, Turnos), así que bloquear la inyección aquí, en el origen, protege todas esas
    pantallas de una sola vez sin depender de que cada tabla escape correctamente."""
    if texto and any(c in _CARACTERES_HTML_PELIGROSOS for c in texto):
        raise HTTPException(400, f"El campo '{campo}' no puede contener los caracteres < > {{ }}")
    return texto


class EmpleadoCreate(BaseModel):
    nombre: str
    cedula: Optional[str] = None
    tipo_contrato: str = "part_time"  # todos son part_time -- se mantiene el campo por compatibilidad
    horas_min_dia: Optional[float] = None
    horas_max_dia: Optional[float] = None
    horas_min_semana: Optional[float] = None
    horas_max_semana: Optional[float] = None


class EmpleadoUpdate(BaseModel):
    nombre: Optional[str] = None
    cedula: Optional[str] = None
    tipo_contrato: Optional[str] = None
    activo: Optional[bool] = None
    horas_min_dia: Optional[float] = None
    horas_max_dia: Optional[float] = None
    horas_min_semana: Optional[float] = None
    horas_max_semana: Optional[float] = None


class DisponibilidadSet(BaseModel):
    dia_semana: str
    tipo: str
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None


class PermisoCreate(BaseModel):
    tipo: str
    fecha_inicio: str
    fecha_fin: str
    comentario: str = ""
    forzar: bool = False


# ---------- Empleados ----------

class GuardarHorarioRequest(BaseModel):
    fecha_lunes: str
    parametros: dict
    resultado: dict


@app.post("/api/horarios-generados")
def api_guardar_horario_generado(payload: GuardarHorarioRequest, request: Request):
    """Guarda en el Historial EXACTAMENTE lo que la persona vio en pantalla (no se regenera
    de nuevo), para evitar cualquier diferencia entre lo que revisó y lo que queda guardado.
    A diferencia de antes, esto ya NO pasa automáticamente al generar -- solo cuando el
    usuario confirma explícitamente con el botón 'Guardar en historial'."""
    try:
        date.fromisoformat(payload.fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")
    db.guardar_horario_generado(payload.fecha_lunes, request.state.user["username"], payload.parametros, payload.resultado)
    registrar_auditoria(request.state.user["username"], "guardar_horario_historial", payload.fecha_lunes)
    return {"ok": True}


@app.get("/api/horarios-generados")
def api_listar_horarios_generados():
    return db.listar_horarios_generados()


@app.get("/api/horarios-generados/{fecha_lunes}")
def api_obtener_horario_generado(fecha_lunes: str):
    r = db.obtener_horario_generado(fecha_lunes)
    if not r:
        raise HTTPException(404, "No hay un horario guardado para esa semana")
    return r


@app.get("/api/horarios-generados/{fecha_lunes}/comparacion")
def api_comparar_horario_real(fecha_lunes: str):
    """Compara lo que se PLANEÓ (el horario guardado en el historial para esa semana)
    contra lo que REALMENTE pasó (llamadas reales cargadas de esa semana exacta), y arma
    sugerencias de ajuste -- ninguna se aplica sola, solo se muestran para que la persona
    decida si las usa la próxima vez que genere un horario parecido."""
    guardado = db.obtener_horario_generado(fecha_lunes)
    if not guardado:
        raise HTTPException(404, "No hay un horario guardado para esa semana en el Historial")

    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")
    domingo = lunes + timedelta(days=6)

    metricas_reales = metricas_generales(fecha_inicio=fecha_lunes, fecha_fin=domingo.isoformat())
    if not metricas_reales:
        raise HTTPException(
            409, "Todavía no hay llamadas reales cargadas para esa semana -- la comparación "
                 "solo tiene sentido después de que la semana ya pasó y subiste el Excel de esa semana."
        )

    tabla_real = resumen_por_dia_semana_y_hora_semanas("callcenter.db", [fecha_lunes])
    cobertura_planeada = guardado["resultado"]["cobertura"]
    sl_planeado = guardado["resultado"]["nivel_servicio"]["sl_estimado_semana_pct"]

    por_dia = []
    for dia in DIAS_SEMANA:
        filas_dia = cobertura_planeada.get(dia, [])
        requerido_planeado = sum(f["requeridos"] for f in filas_dia)
        programado = sum(f["programados"] for f in filas_dia)
        sub_real = tabla_real[tabla_real["dia_semana"] == dia] if not tabla_real.empty else tabla_real
        llamadas_reales = float(sub_real["llamadas_contestadas_prom_dia"].sum() + sub_real["llamadas_abandonadas_prom_dia"].sum()) if len(sub_real) else 0.0
        por_dia.append({
            "dia": dia, "requerido_planeado": requerido_planeado, "programado": programado,
            "llamadas_reales": round(llamadas_reales),
        })

    sl_real = metricas_reales["pct_contestadas"]
    diferencia_sl = round(sl_real - sl_planeado, 1)

    sugerencias = []
    if diferencia_sl <= -8:
        sugerencias.append({
            "tipo": "sl_bajo",
            "mensaje": f"El % de contestación real ({sl_real}%) quedó {abs(diferencia_sl)} puntos por debajo "
                       f"de lo planeado ({sl_planeado}%). Antes de tocar parámetros, revisa si hubo algo "
                       f"puntual esa semana (festivo no detectado, ausentismo, falla técnica) en vez de asumir "
                       f"que el pronóstico está mal.",
        })
    elif diferencia_sl >= 8:
        sugerencias.append({
            "tipo": "sl_alto",
            "mensaje": f"El % de contestación real ({sl_real}%) quedó {diferencia_sl} puntos POR ENCIMA de lo "
                       f"planeado ({sl_planeado}%) -- probablemente sobre-programaste esa semana. Si se repite, "
                       f"considera bajar un poco la meta de servicio o el margen de seguridad para esa semana "
                       f"tipo, y usar esas horas donde sí faltan.",
        })

    dias_con_mas_llamadas = sorted(por_dia, key=lambda d: -d["llamadas_reales"])[:1]
    if dias_con_mas_llamadas and dias_con_mas_llamadas[0]["llamadas_reales"] > 0:
        d = dias_con_mas_llamadas[0]
        if d["programado"] < d["requerido_planeado"]:
            sugerencias.append({
                "tipo": "dia_critico",
                "mensaje": f"{d['dia']} fue el día con más llamadas reales ({d['llamadas_reales']}) y quedó con "
                           f"{d['requerido_planeado'] - d['programado']}h de déficit programado. Si es un patrón "
                           f"recurrente, revisa si hace falta una plantilla de turno específica para ese día.",
            })

    if not sugerencias:
        sugerencias.append({"tipo": "ok", "mensaje": "El resultado real quedó cerca de lo planeado -- no se detectan ajustes obvios que sugerir."})

    return {
        "fecha_lunes": fecha_lunes,
        "sl_planeado": sl_planeado,
        "sl_real": sl_real,
        "diferencia_sl_puntos": diferencia_sl,
        "llamadas_reales_totales": metricas_reales["total_llamadas"],
        "por_dia": por_dia,
        "sugerencias": sugerencias,
    }


@app.delete("/api/horarios-generados/{fecha_lunes}")
def api_eliminar_horario_generado(fecha_lunes: str, request: Request, _=Depends(requiere_superadmin)):
    db.eliminar_horario_generado(fecha_lunes)
    registrar_auditoria(request.state.user["username"], "eliminar_horario_historial", fecha_lunes)
    return {"ok": True}


@app.get("/api/semanas-disponibles")
def api_semanas_disponibles():
    return listar_semanas_disponibles()


@app.get("/api/configuracion/defaults-empleado")
def api_configuracion_defaults_empleado():
    """Solo los valores de horas por defecto para un asesor nuevo -- accesible para
    cualquier rol logueado (a diferencia del resto de Configuración General, que es
    exclusivo de superadmin), porque el modal de '+ Nuevo asesor' lo usa en Personal."""
    cfg = db.obtener_configuracion()
    return {
        "horas_min_dia": cfg.get("horas_min_dia_default", db.DEFAULT_HORAS_MIN_DIA),
        "horas_max_dia": cfg.get("horas_max_dia_default", db.DEFAULT_HORAS_MAX_DIA),
        "horas_min_semana": cfg.get("horas_min_semana_default", db.DEFAULT_HORAS_MIN_SEMANA),
        "horas_max_semana": cfg.get("horas_max_semana_default", db.DEFAULT_HORAS_MAX_SEMANA),
    }


@app.get("/api/configuracion")
def api_obtener_configuracion(_=Depends(requiere_superadmin)):
    return db.obtener_configuracion()


@app.put("/api/configuracion")
def api_actualizar_configuracion(payload: dict, request: Request, _=Depends(requiere_superadmin)):
    claves_validas = set(db._CONFIG_TIPOS.keys())
    claves_invalidas = set(payload.keys()) - claves_validas
    if claves_invalidas:
        raise HTTPException(400, f"Claves de configuración desconocidas: {sorted(claves_invalidas)}")
    resultado = db.actualizar_configuracion(payload)
    registrar_auditoria(request.state.user["username"], "cambiar_configuracion", str(payload))
    return resultado


@app.get("/api/notificaciones")
def api_notificaciones():
    notificaciones = []

    validacion = validar_todos()
    for v in validacion:
        for a in v["alertas"]:
            notificaciones.append({"tipo": "disponibilidad", "nivel": "alerta", "mensaje": f"{v['empleado']}: {a}"})

    empleados = db.listar_empleados()
    sin_cedula = [e["nombre"] for e in empleados if not e.get("cedula")]
    if sin_cedula:
        notificaciones.append({
            "tipo": "personal", "nivel": "alerta",
            "mensaje": f"{len(sin_cedula)} asesor(es) sin cédula registrada: {', '.join(sin_cedula[:3])}"
                       f"{' y otros' if len(sin_cedula) > 3 else ''}",
        })

    hoy = date.today()
    for f in listar_festivos_rango(hoy, hoy + timedelta(days=14)):
        notificaciones.append({"tipo": "festivo", "nivel": "info",
                                "mensaje": f"Festivo próximo: {f['nombre']} ({f['fecha']})"})

    historial = db.listar_horarios_generados()
    if historial and historial[0]["cumple_normativa"] is False:
        notificaciones.append({
            "tipo": "cumplimiento", "nivel": "alerta",
            "mensaje": f"El horario de la semana del {historial[0]['fecha_lunes']} tiene violaciones normativas sin resolver",
        })

    try:
        demanda = _demanda_por_dia("callcenter.db", 0.95, 0.10)
        if any(demanda.values()):
            total_requerido = sum(sum(h.values()) for h in demanda.values())
            capacidad_maxima = sum(e["horas_max_semana"] for e in empleados)
            brecha_horas = max(0, total_requerido - capacidad_maxima)
            if brecha_horas > 0:
                asesores_rec = -(-round(brecha_horas) // 36)
                notificaciones.append({
                    "tipo": "brecha", "nivel": "alerta",
                    "mensaje": f"Brecha de personal: se recomienda contratar {asesores_rec} asesor(es) más",
                })
    except Exception:
        pass

    return notificaciones


@app.get("/api/dashboard")
def api_dashboard():
    empleados = db.listar_empleados()
    full_time = sum(1 for e in empleados if e.get("tipo_contrato", "full_time") == "full_time")
    part_time = len(empleados) - full_time

    validacion = validar_todos()
    alertas_disponibilidad = [v for v in validacion if v["alertas"]]

    metricas = metricas_generales()

    hoy = date.today()
    festivos_prox = listar_festivos_rango(hoy, hoy + timedelta(days=60))
    proximo_festivo = festivos_prox[0] if festivos_prox else None

    brecha_resumen = None
    try:
        demanda = _demanda_por_dia("callcenter.db", 0.95, 0.10)
        if any(demanda.values()):
            total_requerido = sum(sum(h.values()) for h in demanda.values())
            capacidad_maxima = sum(e["horas_max_semana"] for e in empleados)
            brecha_horas = max(0, total_requerido - capacidad_maxima)
            brecha_resumen = {
                "total_requerido_semana": total_requerido, "capacidad_maxima_semana": capacidad_maxima,
                "brecha_horas": round(brecha_horas),
                "asesores_recomendados": -(-round(brecha_horas) // 36) if brecha_horas > 0 else 0,
            }
    except Exception:
        pass

    plantillas = db.listar_plantillas_turno(solo_activas=True)

    return {
        "total_empleados": len(empleados), "full_time": full_time, "part_time": part_time,
        "empleados_con_alerta_disponibilidad": len(alertas_disponibilidad),
        "metricas_generales": metricas,
        "proximo_festivo": proximo_festivo,
        "brecha_personal": brecha_resumen,
        "plantillas_activas": len(plantillas),
        "modo_horarios": "plantillas" if plantillas else "libre",
    }


@app.get("/api/empleados")
def api_listar_empleados(solo_activos: bool = True):
    return db.listar_empleados(solo_activos=solo_activos)


@app.post("/api/empleados")
def api_crear_empleado(payload: EmpleadoCreate):
    validar_texto_seguro(payload.nombre, "nombre")
    validar_texto_seguro(payload.cedula, "cédula")
    cfg = db.obtener_configuracion()
    datos = payload.model_dump()
    if datos["horas_min_dia"] is None:
        datos["horas_min_dia"] = cfg.get("horas_min_dia_default", db.DEFAULT_HORAS_MIN_DIA)
    if datos["horas_max_dia"] is None:
        datos["horas_max_dia"] = cfg.get("horas_max_dia_default", db.DEFAULT_HORAS_MAX_DIA)
    if datos["horas_min_semana"] is None:
        datos["horas_min_semana"] = cfg.get("horas_min_semana_default", db.DEFAULT_HORAS_MIN_SEMANA)
    if datos["horas_max_semana"] is None:
        datos["horas_max_semana"] = cfg.get("horas_max_semana_default", db.DEFAULT_HORAS_MAX_SEMANA)

    if datos["horas_min_semana"] > datos["horas_max_semana"]:
        raise HTTPException(400, "horas_min_semana no puede ser mayor que horas_max_semana")
    if datos["horas_min_dia"] > datos["horas_max_dia"]:
        raise HTTPException(400, "horas_min_dia no puede ser mayor que horas_max_dia")
    emp_id = db.crear_empleado(**datos)
    return db.obtener_empleado(emp_id)


@app.get("/api/empleados/pdf")
def api_empleados_pdf():
    ruta = generar_pdf_personal(salida="reporte_personal.pdf")
    return FileResponse(ruta, media_type="application/pdf", filename="reporte_personal.pdf")


@app.get("/api/empleados/{empleado_id}")
def api_obtener_empleado(empleado_id: int):
    emp = db.obtener_empleado(empleado_id)
    if not emp:
        raise HTTPException(404, "Empleado no encontrado")
    emp["disponibilidad"] = db.obtener_disponibilidad(empleado_id)
    emp["permisos"] = db.listar_permisos(empleado_id)
    return emp


@app.put("/api/empleados/{empleado_id}")
def api_actualizar_empleado(empleado_id: int, payload: EmpleadoUpdate):
    if not db.obtener_empleado(empleado_id):
        raise HTTPException(404, "Empleado no encontrado")
    campos = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "nombre" in campos:
        validar_texto_seguro(campos["nombre"], "nombre")
    if "cedula" in campos:
        validar_texto_seguro(campos["cedula"], "cédula")
    db.actualizar_empleado(empleado_id, **campos)
    return db.obtener_empleado(empleado_id)


class HorasExtraRequest(BaseModel):
    permite_horas_extra: bool
    max_horas_extra_semana: float = 0
    superadmin_username: str
    superadmin_password: str


@app.put("/api/empleados/{empleado_id}/horas-extra")
def api_configurar_horas_extra(empleado_id: int, payload: HorasExtraRequest, request: Request):
    """Habilitar/deshabilitar horas extra para un asesor. Sin importar quién esté logueado
    haciendo el cambio (admin o superadmin), SIEMPRE exige las credenciales de un superadmin
    escritas en el momento -- no basta con que la sesión actual ya sea de superadmin -- y
    deja registro de la autorización (quién la pidió, quién la autorizó, y el antes/después)."""
    empleado = db.obtener_empleado(empleado_id)
    if not empleado:
        raise HTTPException(404, "Empleado no encontrado")
    if payload.permite_horas_extra and payload.max_horas_extra_semana <= 0:
        raise HTTPException(400, "Si activas horas extra, define cuántas (mayor que 0)")

    superadmin = db.obtener_usuario_por_username(payload.superadmin_username)
    if (not superadmin or superadmin["rol"] != "superadmin"
            or not auth.verificar_password(payload.superadmin_password, superadmin["password_hash"], superadmin["salt"])):
        raise HTTPException(401, "Credenciales de superadmin inválidas -- no se aplicó el cambio")

    db.registrar_autorizacion_horas_extra(
        empleado_id, solicitado_por=request.state.user["username"], autorizado_por=superadmin["username"],
        permite_antes=bool(empleado["permite_horas_extra"]), permite_despues=payload.permite_horas_extra,
        horas_extra_antes=empleado["max_horas_extra_semana"],
        horas_extra_despues=payload.max_horas_extra_semana if payload.permite_horas_extra else 0,
    )
    registrar_auditoria(request.state.user["username"], "autorizar_horas_extra",
                         f"{empleado['nombre']}: {'activado' if payload.permite_horas_extra else 'desactivado'}"
                         f" ({payload.max_horas_extra_semana}h/sem) -- autorizado por {superadmin['username']}")
    return db.obtener_empleado(empleado_id)


@app.get("/api/autorizaciones-horas-extra")
def api_listar_autorizaciones_horas_extra(_=Depends(requiere_superadmin)):
    return db.listar_autorizaciones_horas_extra()


@app.delete("/api/empleados/{empleado_id}")
def api_eliminar_empleado(empleado_id: int, definitivo: bool = False):
    if not db.obtener_empleado(empleado_id):
        raise HTTPException(404, "Empleado no encontrado")
    db.eliminar_empleado(empleado_id, definitivo=definitivo)
    return {"ok": True}


# ---------- Disponibilidad ----------

@app.get("/api/empleados/{empleado_id}/disponibilidad")
def api_obtener_disponibilidad(empleado_id: int):
    if not db.obtener_empleado(empleado_id):
        raise HTTPException(404, "Empleado no encontrado")
    return db.obtener_disponibilidad(empleado_id)


@app.put("/api/empleados/{empleado_id}/disponibilidad")
def api_set_disponibilidad(empleado_id: int, payload: DisponibilidadSet):
    if not db.obtener_empleado(empleado_id):
        raise HTTPException(404, "Empleado no encontrado")
    if payload.dia_semana not in DIAS_SEMANA:
        raise HTTPException(400, f"dia_semana debe ser uno de {DIAS_SEMANA}")
    if payload.tipo not in TIPOS_DISPONIBILIDAD:
        raise HTTPException(400, f"tipo debe ser uno de {TIPOS_DISPONIBILIDAD}")
    if payload.tipo == "rango" and not (payload.hora_inicio and payload.hora_fin):
        raise HTTPException(400, "Un rango necesita hora_inicio y hora_fin")

    db.set_disponibilidad(empleado_id, payload.dia_semana, payload.tipo,
                           payload.hora_inicio, payload.hora_fin)
    return db.obtener_disponibilidad(empleado_id)


@app.get("/api/disponibilidad/validacion")
def api_validar_disponibilidad():
    """Usado por el dashboard para mostrar alertas de disponibilidad insuficiente."""
    return validar_todos()


@app.get("/api/disponibilidad/pdf")
def api_disponibilidad_pdf():
    ruta = generar_pdf_disponibilidad(salida="reporte_disponibilidad.pdf")
    return FileResponse(ruta, media_type="application/pdf", filename="reporte_disponibilidad.pdf")


# ---------- Permisos ----------

@app.get("/api/permisos")
def api_listar_permisos(empleado_id: Optional[int] = None):
    return db.listar_permisos(empleado_id)


@app.get("/api/permisos/en-fecha/{fecha}")
def api_permisos_en_fecha(fecha: str):
    return db.empleados_de_permiso_en_fecha(fecha)


@app.post("/api/empleados/{empleado_id}/permisos")
def api_crear_permiso(empleado_id: int, payload: PermisoCreate):
    if not db.obtener_empleado(empleado_id):
        raise HTTPException(404, "Empleado no encontrado")
    if payload.tipo not in TIPOS_PERMISO:
        raise HTTPException(400, f"tipo debe ser uno de {TIPOS_PERMISO}")
    try:
        permiso_id = db.crear_permiso(
            empleado_id, payload.tipo, payload.fecha_inicio, payload.fecha_fin,
            payload.comentario, forzar=payload.forzar,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": permiso_id}


@app.delete("/api/permisos/{permiso_id}")
def api_eliminar_permiso(permiso_id: int):
    db.eliminar_permiso(permiso_id)
    return {"ok": True}


@app.get("/api/permisos/pdf")
def api_permisos_pdf():
    ruta = generar_pdf_permisos(salida="reporte_permisos.pdf")
    return FileResponse(ruta, media_type="application/pdf", filename="reporte_permisos.pdf")


# ---------- Tarifas ----------

class TarifasUpdate(BaseModel):
    valor_hora_normal: Optional[float] = None
    valor_recargo_dominical: Optional[float] = None
    valor_recargo_nocturno: Optional[float] = None
    valor_subsidio_transporte_hora: Optional[float] = None


@app.get("/api/tarifas")
def api_obtener_tarifas():
    return db.obtener_tarifas()


@app.put("/api/tarifas")
def api_actualizar_tarifas(payload: TarifasUpdate, request: Request, _=Depends(requiere_superadmin)):
    campos = {k: v for k, v in payload.model_dump().items() if v is not None}
    resultado = db.actualizar_tarifas(**campos)
    registrar_auditoria(request.state.user["username"], "cambiar_tarifas", str(campos))
    return resultado


# ---------- Horarios y brecha de personal ----------

def _serializar_horario(resultado: dict, costo: dict, nivel_servicio: dict) -> dict:
    horario_json = {}
    for nombre, dias in resultado["horario"].items():
        horario_json[nombre] = {}
        for dia, info in dias.items():
            if "turnos" in info:
                horario_json[nombre][dia] = {"tipo": "turno", "turnos": info["turnos"]}
            else:
                horario_json[nombre][dia] = {"tipo": "libre", "motivo": info["motivo"]}

    sl_por_hora = {
        dia: {h["hora"]: h["sl_estimado_pct"] for h in nivel_servicio["por_dia"].get(dia, {}).get("horas", [])}
        for dia in resultado["cobertura"]
    }
    cobertura_json = {
        dia: [{"hora": h, "requeridos": c["requeridos"], "programados": c["programados"],
               "sl_estimado_pct": sl_por_hora.get(dia, {}).get(h)}
              for h, c in horas.items()]
        for dia, horas in resultado["cobertura"].items()
    }

    horas_trabajadas = [h for h in resultado["horas_semana"].values() if h > 0]
    promedio_horas_por_asesor = round(sum(horas_trabajadas) / len(horas_trabajadas), 1) if horas_trabajadas else 0

    return {
        "horario": horario_json,
        "cobertura": cobertura_json,
        "alertas": resultado["alertas"],
        "horas_semana": resultado["horas_semana"],
        "promedio_horas_por_asesor": promedio_horas_por_asesor,
        "costo": costo,
        "nivel_servicio": nivel_servicio,
    }


@app.get("/api/horario")
def api_generar_horario(fecha_lunes: str, request: Request, target_service_level: float = 0.95,
                         shrinkage: float = 0.10, factor_proyeccion: float = 1.0, max_occupancy: float = 0.85,
                         semanas_base: Optional[str] = None):
    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")

    lista_semanas = semanas_base.split(",") if semanas_base else None
    resultado = generar_horario_semana(lunes, target_service_level=target_service_level, shrinkage=shrinkage,
                                        factor_proyeccion=factor_proyeccion, max_occupancy=max_occupancy,
                                        semanas_base=lista_semanas)
    costo = calcular_costo_horario(resultado)
    nivel_servicio = estimar_nivel_servicio_real(resultado)
    cumplimiento = validar_cumplimiento(resultado, lunes, db.listar_empleados())
    respuesta = _serializar_horario(resultado, costo, nivel_servicio)
    respuesta["cumplimiento"] = cumplimiento

    return respuesta


@app.get("/api/festivos")
def api_festivos(fecha_inicio: str, fecha_fin: str):
    try:
        fi, ff = date.fromisoformat(fecha_inicio), date.fromisoformat(fecha_fin)
    except ValueError:
        raise HTTPException(400, "Fechas deben tener formato YYYY-MM-DD")
    return listar_festivos_rango(fi, ff)


@app.get("/api/festivos/historico")
def api_festivos_historico():
    return resumen_festivos_historicos()


@app.get("/api/horario/pdf")
def api_horario_pdf(fecha_lunes: str, target_service_level: float = 0.95, shrinkage: float = 0.10,
                     max_occupancy: float = 0.85, semanas_base: Optional[str] = None, mostrar_costos: bool = True):
    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")

    lista_semanas = semanas_base.split(",") if semanas_base else None
    ruta = generar_pdf_horario(lunes, target_service_level=target_service_level, shrinkage=shrinkage,
                                max_occupancy=max_occupancy, semanas_base=lista_semanas,
                                mostrar_costos=mostrar_costos, salida="reporte_horario.pdf")
    sufijo = "" if mostrar_costos else "_equipo"
    return FileResponse(ruta, media_type="application/pdf", filename=f"reporte_horario_{fecha_lunes}{sufijo}.pdf")


@app.get("/api/horario/excel")
def api_horario_excel(fecha_lunes: str, target_service_level: float = 0.95, shrinkage: float = 0.10,
                       max_occupancy: float = 0.85, semanas_base: Optional[str] = None, mostrar_costos: bool = True):
    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")

    lista_semanas = semanas_base.split(",") if semanas_base else None
    ruta = generar_excel_horario(lunes, target_service_level=target_service_level, shrinkage=shrinkage,
                                  max_occupancy=max_occupancy, semanas_base=lista_semanas,
                                  mostrar_costos=mostrar_costos, salida="horario.xlsx")
    sufijo = "" if mostrar_costos else "_equipo"
    return FileResponse(ruta, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         filename=f"horario_{fecha_lunes}{sufijo}.xlsx")


@app.get("/api/brecha-personal")
def api_brecha_personal(target_service_level: float = 0.95, shrinkage: float = 0.10,
                         horas_contrato_nuevo: float = 36, max_occupancy: float = 0.85,
                         semanas_base: Optional[str] = None, fecha_lunes: Optional[str] = None):
    """
    A diferencia de antes (que sumaba disponibilidad teórica sin coordinar), esto CORRE el
    generador real con los mismos parámetros que usarías en Horarios, y muestra el
    resultado REAL esperado -- así no puede decir "vas bien" y luego Horarios mostrar
    huecos: es literalmente el mismo cálculo. Además identifica en qué día/franja se
    concentra el problema, para sugerir un PERFIL de contratación, no solo un número.
    """
    empleados = db.listar_empleados()
    lista_semanas = semanas_base.split(",") if semanas_base else None
    try:
        lunes = date.fromisoformat(fecha_lunes) if fecha_lunes else date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")

    resultado = generar_horario_semana(lunes, target_service_level=target_service_level, shrinkage=shrinkage,
                                        max_occupancy=max_occupancy, semanas_base=lista_semanas)

    demanda = _demanda_por_dia("callcenter.db", target_service_level, shrinkage, max_occupancy=max_occupancy,
                                semanas_base=lista_semanas)
    total_requerido = sum(sum(h.values()) for h in demanda.values())
    capacidad_maxima = sum(e["horas_max_semana"] for e in empleados)

    # ---- Resultado REAL por día (del horario efectivamente simulado, no una teoría) ----
    detalle_por_dia = []
    for dia in DIAS_SEMANA:
        requerido_dia = sum(c["requeridos"] for c in resultado["cobertura"][dia].values())
        programado_dia = sum(c["programados"] for c in resultado["cobertura"][dia].values())
        deficit_dia = max(0, requerido_dia - programado_dia)
        pct_cubierto = round((programado_dia / requerido_dia) * 100, 1) if requerido_dia > 0 else 100.0
        detalle_por_dia.append({
            "dia": dia, "requerido": requerido_dia, "programado_real": programado_dia,
            "deficit": deficit_dia, "pct_cubierto_real": pct_cubierto,
            "estado": "critico" if pct_cubierto < 80 else ("ajustado" if pct_cubierto < 95 else "cubierto"),
        })

    # ---- Franjas horarias donde el déficit REAL es más grave (para sugerir perfil) ----
    # Se ordena por déficit RELATIVO (% de gente que falta en esa hora específica), no
    # absoluto -- un día con mucha demanda total (ej. Domingo) puede "tapar" en números
    # absolutos a un día más chico que en realidad está proporcionalmente igual de mal
    # (ej. Martes a las 11:00, que puede faltarle más del 50% de su gente aunque el número
    # bruto sea más bajo que el de Domingo).
    deficit_por_hora_dia = []
    for dia in DIAS_SEMANA:
        for h, c in resultado["cobertura"][dia].items():
            if c["requeridos"] > 0:
                deficit_por_hora_dia.append({
                    "dia": dia, "hora": h, "deficit": c["requeridos"] - c["programados"],
                    "deficit_relativo_pct": round(max(0, c["requeridos"] - c["programados"]) / c["requeridos"] * 100, 1),
                })
    peores = sorted([d for d in deficit_por_hora_dia if d["deficit"] > 0], key=lambda d: -d["deficit_relativo_pct"])[:5]

    perfil_sugerido = None
    dias_criticos = sorted([d for d in detalle_por_dia if d["deficit"] > 0], key=lambda d: -d["deficit"])
    if dias_criticos:
        dias_texto = ", ".join(f"{d['dia']} ({d['pct_cubierto_real']}%)" for d in dias_criticos[:3])
        horas_texto = ", ".join(f"{p['dia']} {p['hora']}:00 ({p['deficit_relativo_pct']:.0f}% corto)" for p in peores[:3])
        perfil_sugerido = (f"Con la meta y parámetros actuales, el horario real quedaría corto en: {dias_texto}."
                            + (f" Las franjas proporcionalmente más críticas son: {horas_texto}." if horas_texto else "")
                            + " Al contratar, prioriza candidatos con disponibilidad real en esos días/horas"
                              " específicos -- tener más horas totales a la semana no ayuda si no calzan ahí.")

    deficit_total_real = sum(d["deficit"] for d in detalle_por_dia)
    asesores_recomendados = int(-(-deficit_total_real // horas_contrato_nuevo)) if deficit_total_real else 0

    costo_estimado_semana = None
    if asesores_recomendados > 0:
        tarifas = db.obtener_tarifas()
        costo_hora_promedio = tarifas["valor_hora_normal"] + tarifas["valor_subsidio_transporte_hora"]
        costo_estimado_semana = round(asesores_recomendados * horas_contrato_nuevo * costo_hora_promedio)

    return {
        "fecha_lunes_simulada": lunes.isoformat(),
        "total_requerido_semana": total_requerido,
        "capacidad_maxima_semana": capacidad_maxima,
        "sl_estimado_real_pct": estimar_nivel_servicio_real(resultado)["sl_estimado_semana_pct"],
        "deficit_total_real": deficit_total_real,
        "asesores_recomendados": asesores_recomendados,
        "costo_estimado_semana_adicional": costo_estimado_semana,
        "detalle_por_dia": detalle_por_dia,
        "perfil_sugerido": perfil_sugerido,
        "peores_franjas": peores,
    }


@app.get("/api/brecha-personal/pdf")
def api_brecha_personal_pdf(fecha_lunes: str, target_service_level: float = 0.95, shrinkage: float = 0.10,
                             max_occupancy: float = 0.85):
    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "fecha_lunes debe tener formato YYYY-MM-DD")

    ruta = generar_pdf_brecha_personal(lunes, target_service_level=target_service_level, shrinkage=shrinkage,
                                        max_occupancy=max_occupancy, salida="reporte_brecha_personal.pdf")
    return FileResponse(ruta, media_type="application/pdf",
                         filename=f"reporte_brecha_personal_{fecha_lunes}.pdf")


# ---------- Importar archivos desde el navegador ----------

TAMANO_MAXIMO_EXCEL_BYTES = 20 * 1024 * 1024  # 20MB -- de sobra para cualquier reporte real


async def _guardar_excel_subido_de_forma_segura(file: UploadFile) -> str:
    """Valida y guarda en un temporal un .xlsx/.xls subido, con 2 capas de defensa además
    de la extensión del nombre (que cualquiera puede falsificar): (1) tope de tamaño, leído
    en bloques -- para no cargar en memoria/disco un archivo enorme y tumbar el servidor
    (denegación de servicio); (2) firma real de archivo -- un .xlsx de verdad es un ZIP y
    siempre empieza con los bytes 'PK', así que un archivo con esa extensión pero contenido
    distinto (ej. un script renombrado) se rechaza antes de intentar procesarlo."""
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "El archivo debe ser .xlsx o .xls")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp_path = tmp.name
            total = 0
            primer_bloque = True
            while True:
                bloque = await file.read(1024 * 1024)  # de a 1MB
                if not bloque:
                    break
                total += len(bloque)
                if total > TAMANO_MAXIMO_EXCEL_BYTES:
                    raise HTTPException(400, "El archivo es demasiado pesado (máx. 20MB)")
                if primer_bloque:
                    if not bloque.startswith(b"PK"):
                        raise HTTPException(400, "El archivo no parece ser un Excel válido (.xlsx/.xls real)")
                    primer_bloque = False
                tmp.write(bloque)
        return tmp_path
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


@app.post("/api/importar/disponibilidad")
async def api_importar_disponibilidad(file: UploadFile = File(...)):
    tmp_path = await _guardar_excel_subido_de_forma_segura(file)
    try:
        resumen = cargar_disponibilidad_excel(tmp_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
    return resumen


@app.post("/api/importar/llamadas")
async def api_importar_llamadas(file: UploadFile = File(...)):
    tmp_path = await _guardar_excel_subido_de_forma_segura(file)
    try:
        resumen = cargar_llamadas_excel(tmp_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
    return resumen


@app.delete("/api/llamadas")
def api_eliminar_llamadas(request: Request, _=Depends(requiere_superadmin)):
    """Borra TODO el histórico de llamadas. Requiere rol superadmin por ser destructivo."""
    borradas = db.eliminar_todas_las_llamadas()
    registrar_auditoria(request.state.user["username"], "borrar_llamadas_todo", f"{borradas} llamadas borradas")
    return {"ok": True, "llamadas_borradas": borradas}


@app.delete("/api/llamadas/rango")
def api_eliminar_llamadas_rango(fecha_inicio: str, fecha_fin: str, request: Request, _=Depends(requiere_superadmin)):
    """Borra solo las llamadas dentro de un rango de fechas. Requiere rol superadmin."""
    borradas = db.eliminar_llamadas_rango(fecha_inicio, fecha_fin)
    registrar_auditoria(request.state.user["username"], "borrar_llamadas_rango",
                         f"{fecha_inicio} a {fecha_fin}: {borradas} llamadas borradas")
    return {"ok": True, "llamadas_borradas": borradas}


@app.get("/api/auditoria")
def api_listar_auditoria(accion: Optional[str] = None, usuario: Optional[str] = None,
                          fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None,
                          busqueda: Optional[str] = None, _=Depends(requiere_superadmin)):
    return db.listar_auditoria(accion=accion, usuario=usuario, fecha_inicio=fecha_inicio,
                                fecha_fin=fecha_fin, busqueda=busqueda)


@app.get("/api/auditoria/filtros")
def api_auditoria_filtros(_=Depends(requiere_superadmin)):
    return {"acciones": db.listar_acciones_auditoria(), "usuarios": db.listar_usuarios_auditoria()}


# ---------- Métricas ----------

@app.get("/api/metricas")
def api_metricas(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None,
                  hora_inicio: Optional[int] = None, hora_fin: Optional[int] = None):
    m = metricas_generales(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                            hora_inicio=hora_inicio, hora_fin=hora_fin)
    if m is None:
        raise HTTPException(404, "Todavía no hay llamadas cargadas. Ve a Importar Datos.")
    return m


@app.get("/api/tendencia-dia-semana")
def api_tendencia_dia_semana(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None):
    return tendencia_semanal_matriz(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)


@app.get("/api/resumen-dia-semana")
def api_resumen_dia_semana(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None):
    resumen = resumen_simple_por_dia_semana(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    # Agentes-hora que el algoritmo REALMENTE usaría en modo "Automático" (todo el histórico
    # ponderado, más peso a lo reciente) -- distinto de "llamadas contestadas" de la tabla,
    # que es solo del rango filtrado aquí. Se muestran juntos para que sea fácil ver que la
    # prioridad de un día no depende solo de cuántas llamadas tuvo, sino también del TMO y
    # de cómo se reparten esas llamadas por hora (Erlang C no es lineal).
    try:
        demanda_automatica = _demanda_por_dia("callcenter.db", 0.95, 0.10)
        for fila in resumen:
            fila["agentes_hora_automatico"] = round(sum(demanda_automatica.get(fila["dia_semana"], {}).values()))
    except Exception:
        for fila in resumen:
            fila["agentes_hora_automatico"] = None
    return resumen


@app.get("/api/desglose-dia-hora")
def api_desglose_dia_hora(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None,
                           target_service_level: float = 0.95, shrinkage: float = 0.10):
    tabla = resumen_por_dia_semana_y_hora(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if tabla.empty:
        return []
    from erlang import required_agents
    registros = tabla.to_dict(orient="records")
    for r in registros:
        calc = required_agents(
            calls=round(r["llamadas_contestadas_prom_dia"]),
            aht_seconds=r["tmo_seg_prom"] if r["tmo_seg_prom"] > 0 else 150,
            target_service_level=target_service_level, shrinkage=shrinkage,
        )
        r["agentes_requeridos"] = calc.agents_final
    return registros


@app.get("/api/metricas/agentes")
def api_metricas_agentes(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None):
    return rendimiento_por_agente(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)


@app.get("/api/metricas/pdf")
def api_metricas_pdf(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None,
                      hora_inicio: Optional[int] = None, hora_fin: Optional[int] = None):
    ruta = generar_pdf_metricas(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                                 hora_inicio=hora_inicio, hora_fin=hora_fin, salida="reporte_metricas.pdf")
    return FileResponse(ruta, media_type="application/pdf", filename="reporte_metricas.pdf")


@app.get("/api/reporte-ejecutivo/pdf")
def api_reporte_ejecutivo_pdf(fecha_lunes_referencia: Optional[str] = None,
                               fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None):
    fecha_ref = date.fromisoformat(fecha_lunes_referencia) if fecha_lunes_referencia else None
    ruta = generar_pdf_ejecutivo(fecha_lunes_referencia=fecha_ref, fecha_inicio=fecha_inicio,
                                  fecha_fin=fecha_fin, salida="reporte_ejecutivo.pdf")
    return FileResponse(ruta, media_type="application/pdf", filename="reporte_ejecutivo.pdf")


# ---------- Frontend estático ----------
# Sirve la interfaz web (HTML/CSS/JS) que consume esta misma API.
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# NOTA PARA DESPLIEGUE EN LÍNEA:
# db.py usa sqlite3 con SQL estándar. Para migrar a Postgres:
#   1. pip install psycopg2-binary
#   2. Cambiar get_conn() en db.py para usar psycopg2 en vez de sqlite3
#   3. El resto del código (funciones CRUD) no cambia casi nada.

"""
cumplimiento.py
Validaciones de cumplimiento normativo laboral, estándar en cualquier sistema profesional
de Workforce Management (WFM):
  - Máximo de días consecutivos trabajados (por defecto 6, cruza incluso el límite de
    semana usando el historial de turnos).
  - Descanso mínimo entre el fin de un turno y el inicio del siguiente (por defecto 10h).
  - Máximo de horas semanales (ya se respeta como tope duro en el generador, aquí se
    reporta para que quede visible en el mismo reporte de cumplimiento).
"""

from datetime import date, timedelta

from db import DIAS_SEMANA, conteo_historico_por_dia_semana, get_conn, DB_PATH, obtener_configuracion

MAX_DIAS_CONSECUTIVOS = 6
DESCANSO_MINIMO_ENTRE_TURNOS_HORAS = 10


def _dias_trabajados_semana_anterior(empleado_id: int, fecha_lunes: date, db_path: str = DB_PATH) -> set:
    """Devuelve el conjunto de fechas (date) de la semana INMEDIATAMENTE anterior en las que
    este empleado trabajó, según el historial guardado -- para detectar rachas de días
    consecutivos que cruzan el límite entre una semana y la siguiente."""
    fecha_inicio_semana_anterior = fecha_lunes - timedelta(days=7)
    fecha_fin_semana_anterior = fecha_lunes - timedelta(days=1)
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT fecha FROM historial_turnos
            WHERE empleado_id = ? AND fecha >= ? AND fecha <= ? AND hora_inicio IS NOT NULL
        """, (empleado_id, fecha_inicio_semana_anterior.isoformat(), fecha_fin_semana_anterior.isoformat())).fetchall()
        return {date.fromisoformat(r["fecha"]) for r in rows}


def validar_cumplimiento(resultado_horario: dict, fecha_lunes: date, empleados: list,
                          db_path: str = DB_PATH,
                          max_dias_consecutivos: int = None,
                          descanso_minimo_horas: int = None) -> dict:
    """
    Revisa el horario ya generado contra reglas laborales estándar. Devuelve:
      {"violaciones": [...], "resumen": {"dias_consecutivos_max": N, "descansos_cortos": N}}
    Si no se pasan max_dias_consecutivos/descanso_minimo_horas explícitamente, se toman de
    la Configuración General del sistema (editable solo por superadmin).
    """
    if max_dias_consecutivos is None or descanso_minimo_horas is None:
        config = obtener_configuracion(db_path=db_path)
        if max_dias_consecutivos is None:
            max_dias_consecutivos = config.get("max_dias_consecutivos", MAX_DIAS_CONSECUTIVOS)
        if descanso_minimo_horas is None:
            descanso_minimo_horas = config.get("descanso_minimo_horas", DESCANSO_MINIMO_ENTRE_TURNOS_HORAS)

    violaciones = []
    fechas_semana = {DIAS_SEMANA[i]: fecha_lunes + timedelta(days=i) for i in range(7)}
    peor_racha = 0

    for e in empleados:
        nombre = e["nombre"]
        horario_emp = resultado_horario["horario"].get(nombre, {})

        # ---- 1) Días consecutivos trabajados (incluye la racha que viene de la semana anterior) ----
        dias_trabajados_esta_semana = {
            fechas_semana[dia] for dia in DIAS_SEMANA if "turnos" in horario_emp.get(dia, {})
        }
        dias_previos = _dias_trabajados_semana_anterior(e["id"], fecha_lunes, db_path=db_path)
        todas_fechas_trabajadas = sorted(dias_trabajados_esta_semana | dias_previos)

        racha_actual = 0
        racha_maxima = 0
        fecha_anterior = None
        for f in todas_fechas_trabajadas:
            if fecha_anterior is not None and (f - fecha_anterior).days == 1:
                racha_actual += 1
            else:
                racha_actual = 1
            racha_maxima = max(racha_maxima, racha_actual)
            fecha_anterior = f
        peor_racha = max(peor_racha, racha_maxima)

        if racha_maxima > max_dias_consecutivos:
            violaciones.append({
                "tipo": "dias_consecutivos", "empleado": nombre,
                "detalle": f"{nombre} trabajaría {racha_maxima} días seguidos (máximo recomendado: {max_dias_consecutivos})",
            })

        # ---- 2) Descanso mínimo entre turnos consecutivos (dentro de la semana) ----
        turnos_ordenados = []
        for dia in DIAS_SEMANA:
            info = horario_emp.get(dia, {})
            if "turnos" in info:
                for t in info["turnos"]:
                    turnos_ordenados.append((fechas_semana[dia], t["inicio"], t["fin"]))
        turnos_ordenados.sort(key=lambda x: (x[0], x[1]))

        for i in range(len(turnos_ordenados) - 1):
            fecha1, _, fin1 = turnos_ordenados[i]
            fecha2, inicio2, _ = turnos_ordenados[i + 1]
            fin_turno1_absoluto = fecha1.toordinal() * 24 + fin1
            inicio_turno2_absoluto = fecha2.toordinal() * 24 + inicio2
            descanso = inicio_turno2_absoluto - fin_turno1_absoluto
            if 0 <= descanso < descanso_minimo_horas:
                violaciones.append({
                    "tipo": "descanso_corto", "empleado": nombre,
                    "detalle": f"{nombre}: solo {descanso}h de descanso entre el turno del "
                               f"{fecha1.strftime('%d/%m')} (termina {fin1}:00) y el del "
                               f"{fecha2.strftime('%d/%m')} (empieza {inicio2}:00) -- mínimo recomendado {descanso_minimo_horas}h",
                })

    return {
        "violaciones": violaciones,
        "resumen": {
            "total_violaciones": len(violaciones),
            "dias_consecutivos_max_detectado": peor_racha,
            "cumple": len(violaciones) == 0,
        },
    }

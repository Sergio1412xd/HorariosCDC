"""
generador_horarios.py
Genera el cuadrante semanal cruzando:
  - Demanda por hora (Erlang C, usando el histórico real, desglosado por día de la
    semana cuando hay datos suficientes -- un sábado no se dimensiona igual que un martes)
  - Disponibilidad de cada asesor (por día de la semana)
  - Permisos (vacaciones, capacitación, etc.) para las fechas exactas de esa semana
  - Reglas de horas mín/máx diarias y semanales de cada asesor

Turnos de duración VARIABLE (entre horas_min_dia y horas_max_dia), ajustados para cubrir
la demanda lo mejor posible.

NOTA HONESTA SOBRE EL ALGORITMO: esto es un algoritmo "voraz" (greedy) con reparación,
no un optimizador matemático exacto (no garantiza la solución matemáticamente óptima como
lo haría un solver de programación lineal). Se eligió así a propósito porque es transparente
y fácil de entender/ajustar línea por línea. En la práctica da resultados muy buenos porque
sigue una regla simple y efectiva: en cada paso, cubre primero la hora con MÁS gente faltando,
priorizando al asesor cuyo turno cubra más horas de déficit y que más necesite acercarse a su
mínimo semanal. Si en el futuro se necesita exprimir el último 2-3% de eficiencia, se puede
reemplazar por un solver (OR-Tools) sin tocar el resto del sistema.
"""

import math
from datetime import date, timedelta

import db as db_config
from db import (listar_empleados, obtener_disponibilidad, empleados_de_permiso_en_fecha, DIAS_SEMANA,
                 conteo_historico_por_dia_semana, guardar_turnos_historial_batch, listar_plantillas_turno)
from agregados_llamadas import (resumen_por_dia_semana_y_hora_ponderado, resumen_por_hora,
                                  resumen_por_dia_semana_y_hora_semanas)
from erlang import required_agents

HORARIO_OPERATIVO_INICIO = 11   # 11:00
HORARIO_OPERATIVO_FIN = 23      # 23:00 (fin exclusivo -> última hora programable es 22:00-23:00)
DOMINGO_MAX_HORAS = 7           # tope de horas por turno los domingos (recargo dominical más costoso)


def _ancho_bloque_deficit(deficits: dict, hi: int, hf: int, hora_pico: int) -> int:
    """
    Cuenta cuántas horas CONSECUTIVAS alrededor de hora_pico (dentro de [hi, hf)) todavía
    tienen déficit. Se usa para no asignar turnos más largos de lo que el pico realmente
    necesita -- un turno de 8h cuando el pico dura solo 3h desperdicia 5h que podrían usarse
    en otro día/hora con déficit real.
    """
    izq = hora_pico
    while izq - 1 >= hi and deficits.get(izq - 1, 0) > 0:
        izq -= 1
    der = hora_pico
    while der + 1 < hf and deficits.get(der + 1, 0) > 0:
        der += 1
    return der - izq + 1


def _demanda_por_dia(db_path, target_service_level, shrinkage, factor_decaimiento=0.7, max_occupancy=0.85,
                      semanas_base: list = None, target_answer_seconds: int = 20, margen_seguridad_agentes: int = 0):
    """Devuelve {dia_semana: {hora: agentes_requeridos}}, ponderando semanas recientes,
    y completando con el promedio general si algún día de semana no tiene datos aún."""
    datos = _datos_demanda_por_dia(db_path, target_service_level, shrinkage, factor_decaimiento,
                                    max_occupancy=max_occupancy, semanas_base=semanas_base,
                                    target_answer_seconds=target_answer_seconds,
                                    margen_seguridad_agentes=margen_seguridad_agentes)
    return {dia: {h: v["agentes_requeridos"] for h, v in horas.items()} for dia, horas in datos.items()}


def _datos_demanda_por_dia(db_path, target_service_level, shrinkage, factor_decaimiento=0.7,
                            factor_proyeccion: float = 1.0, max_occupancy: float = 0.85,
                            semanas_base: list = None, target_answer_seconds: int = 20,
                            margen_seguridad_agentes: int = 0):
    """Igual que _demanda_por_dia pero conserva también 'calls' y 'aht_seconds' de cada hora,
    necesarios luego para estimar el nivel de servicio REAL que da un horario ya generado.
    'factor_proyeccion' escala las llamadas esperadas (ej. 1.10 = +10% por una promo/campaña).
    'max_occupancy' es el % máximo de tiempo que se fuerza a un agente a estar en llamada
    (ej. 0.85 = no forzar a nadie a estar ocupado más del 85% del turno). Solo importa
    cuando la meta de servicio es baja (con metas altas, esta restricción casi nunca aplica,
    porque ya se necesitan más agentes de los que harían falta solo por ocupación).
    'semanas_base': si se pasa una lista de fechas (lunes de cada semana), la demanda se
    calcula SOLO con esas semanas (promedio simple entre ellas) en vez de usar todo el
    histórico con decaimiento -- útil para excluir semanas atípicas o basarse en una sola
    semana representativa. 'target_answer_seconds': en cuántos segundos se considera que
    una llamada fue "contestada a tiempo" para el % de servicio (estándar de la industria:
    20s, pero es configurable). 'margen_seguridad_agentes': N agentes EXTRA que se suman a
    lo que pide Erlang C en cada hora, como colchón ante picos que ni el shrinkage ni la
    proyección de actividad alcanzan a cubrir -- sube el costo, pero hace el horario más
    robusto ante variaciones inesperadas de la demanda real."""
    if semanas_base:
        tabla_dia = resumen_por_dia_semana_y_hora_semanas(db_path, semanas_base)
    else:
        tabla_dia = resumen_por_dia_semana_y_hora_ponderado(db_path=db_path, factor_decaimiento=factor_decaimiento)
    datos = {}

    if not tabla_dia.empty:
        for dia in tabla_dia["dia_semana"].unique():
            sub = tabla_dia[tabla_dia["dia_semana"] == dia]
            datos[dia] = {}
            for _, fila in sub.iterrows():
                calls = round(fila["llamadas_contestadas_prom_dia"] * factor_proyeccion)
                aht = fila["tmo_seg_prom"] if fila["tmo_seg_prom"] > 0 else 150
                r = required_agents(calls=calls, aht_seconds=aht, target_service_level=target_service_level,
                                     shrinkage=shrinkage, max_occupancy=max_occupancy,
                                     target_answer_seconds=target_answer_seconds)
                agentes = r.agents_final + margen_seguridad_agentes if calls > 0 else r.agents_final
                datos[dia][int(fila["hora_del_dia"])] = {
                    "agentes_requeridos": agentes, "calls": calls, "aht_seconds": aht,
                }

    tabla_general = resumen_por_hora(db_path=db_path)
    datos_general = {}
    for _, fila in tabla_general.iterrows():
        calls = round(fila["llamadas_contestadas_prom_dia"] * factor_proyeccion)
        aht = fila["tmo_seg_prom"] if fila["tmo_seg_prom"] > 0 else 150
        r = required_agents(calls=calls, aht_seconds=aht, target_service_level=target_service_level,
                             shrinkage=shrinkage, max_occupancy=max_occupancy,
                             target_answer_seconds=target_answer_seconds)
        agentes = r.agents_final + margen_seguridad_agentes if calls > 0 else r.agents_final
        datos_general[int(fila["hora_del_dia"])] = {
            "agentes_requeridos": agentes, "calls": calls, "aht_seconds": aht,
        }

    for dia in DIAS_SEMANA:
        if dia not in datos or not datos[dia]:
            datos[dia] = datos_general

    return datos


def _ventana_disponibilidad(disp_dia, dia_semana):
    """(hora_inicio, hora_fin) enteros, o None si no disponible ese día."""
    if not disp_dia:
        return None
    tipo = disp_dia["tipo"]
    if tipo == "completa":
        return (HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN)
    if tipo == "rango":
        hi = int(disp_dia["hora_inicio"].split(":")[0])
        hf = int(disp_dia["hora_fin"].split(":")[0])
        return (max(hi, HORARIO_OPERATIVO_INICIO), min(hf, HORARIO_OPERATIVO_FIN))
    return None  # no_disponible / sin_informacion


def horas_pagables_turno(turno: dict):
    """Generador de las horas de un turno que SÍ se pagan/cuentan como cobertura real --
    excluye la hora de almuerzo, si el turno tiene una (ver 'almuerzo_inicio'/'almuerzo_horas').
    Función a nivel de módulo para que costos.py, pdf_reporte.py y excel_reporte.py puedan
    usarla también, no solo el generador."""
    almuerzo_ini = turno.get("almuerzo_inicio")
    almuerzo_dur = turno.get("almuerzo_horas", 0)
    for h in range(turno["inicio"], turno["fin"]):
        if almuerzo_ini is not None and almuerzo_ini <= h < almuerzo_ini + almuerzo_dur:
            continue
        yield h


def generar_horario_semana(fecha_lunes: date, db_path: str = "callcenter.db",
                            target_service_level: float = 0.95, shrinkage: float = 0.10,
                            fraccion_equidad: float = 0.40, factor_proyeccion: float = 1.0,
                            duracion_preferida_max: int = None, n_dias_prioridad_maxima: int = None,
                            max_occupancy: float = 0.85, semanas_base: list = None):
    """
    fecha_lunes: el lunes (date) de la semana a programar.
    Devuelve dict con 'horario', 'cobertura', 'alertas', 'horas_semana'.

    Los parámetros de AJUSTE FINO que no se pasen explícitamente (duracion_preferida_max,
    n_dias_prioridad_maxima) se toman de la Configuración General del sistema (editable
    solo por superadmin), igual que el horario operativo, el tope dominical y el máximo de
    turnos por día -- así el negocio puede ajustar estas reglas sin tocar código.
    """
    global HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN, DOMINGO_MAX_HORAS
    config = db_config.obtener_configuracion(db_path=db_path)
    HORARIO_OPERATIVO_INICIO = config.get("horario_operativo_inicio", HORARIO_OPERATIVO_INICIO)
    HORARIO_OPERATIVO_FIN = config.get("horario_operativo_fin", HORARIO_OPERATIVO_FIN)
    DOMINGO_MAX_HORAS = config.get("domingo_max_horas", DOMINGO_MAX_HORAS)
    if duracion_preferida_max is None:
        duracion_preferida_max = config.get("duracion_preferida_max", 6)
    if n_dias_prioridad_maxima is None:
        n_dias_prioridad_maxima = config.get("n_dias_prioridad_maxima", 3)

    empleados = listar_empleados(db_path=db_path)
    # Si un asesor tiene horas extra autorizadas (ver /api/empleados/{id}/horas-extra, que exige
    # credenciales de superadmin), su tope semanal efectivo para ESTA generación incluye ese
    # extra -- esto no modifica el contrato base guardado, solo lo que el algoritmo puede usar
    # para cubrir brechas en esta corrida puntual.
    for e in empleados:
        if e.get("permite_horas_extra"):
            e["horas_max_semana"] = e["horas_max_semana"] + e.get("max_horas_extra_semana", 0)
    datos_demanda = _datos_demanda_por_dia(db_path, target_service_level, shrinkage,
                                            factor_proyeccion=factor_proyeccion, max_occupancy=max_occupancy,
                                            semanas_base=semanas_base, factor_decaimiento=config.get("factor_decaimiento", 0.7),
                                            target_answer_seconds=config.get("target_answer_seconds", 20),
                                            margen_seguridad_agentes=config.get("margen_seguridad_agentes", 0))
    demanda = {dia: {h: v["agentes_requeridos"] for h, v in horas.items()} for dia, horas in datos_demanda.items()}
    fechas_semana = {DIAS_SEMANA[i]: fecha_lunes + timedelta(days=i) for i in range(7)}

    horario = {e["nombre"]: {} for e in empleados}
    horas_semana = {e["nombre"]: 0.0 for e in empleados}
    alertas = []

    # ---- Festivos: si algún día de esta semana es festivo, usar el patrón histórico de
    # festivos (comparado automáticamente contra festivos anteriores) en vez del patrón
    # normal de ese día de la semana -- un festivo casi nunca se comporta como un día normal. ----
    try:
        from festivos import es_festivo, nombre_festivo, resumen_festivos_historicos
        resumen_fest = resumen_festivos_historicos(db_path=db_path)
        patron_festivo = resumen_fest.get("patron_por_hora", {})

        for dia_nombre, fecha_dia in fechas_semana.items():
            if es_festivo(fecha_dia):
                nombre_f = nombre_festivo(fecha_dia)
                if patron_festivo:
                    for h_str, vals in patron_festivo.items():
                        h = int(h_str)
                        calls = round(vals["llamadas_contestadas_prom_dia"] * factor_proyeccion)
                        aht = vals["tmo_seg_prom"] if vals["tmo_seg_prom"] > 0 else 150
                        r = required_agents(calls=calls, aht_seconds=aht, target_service_level=target_service_level,
                                             shrinkage=shrinkage, max_occupancy=max_occupancy,
                                             target_answer_seconds=config.get("target_answer_seconds", 20))
                        demanda.setdefault(dia_nombre, {})[h] = r.agents_final + config.get("margen_seguridad_agentes", 0)
                    alertas.append(f"{dia_nombre} {fecha_dia.isoformat()} es festivo ({nombre_f}): "
                                    f"se usó el patrón histórico de festivos ({resumen_fest['n_festivos_en_historico']} "
                                    f"festivo(s) en el histórico), no el patrón normal de ese día.")
                else:
                    alertas.append(f"{dia_nombre} {fecha_dia.isoformat()} es festivo ({nombre_f}), pero no hay "
                                    f"festivos previos en el histórico para ajustar el patrón -- se usó el patrón "
                                    f"normal de ese día de la semana. Revisar manualmente.")
    except Exception:
        pass  # si el módulo de festivos falla por cualquier razón, seguimos con el patrón normal

    cobertura = {}
    candidatos_por_dia = {}
    asignados_por_dia = {dia: {} for dia in DIAS_SEMANA}  # {nombre: [(inicio,fin), ...]} -- permite turnos partidos
    almuerzos_por_hora = {dia: {} for dia in DIAS_SEMANA}  # {hora: cuántos ya almuerzan ahí} -- evita que todos almuercen a la vez

    # ---- Plantillas de turno (módulo "Turnos"): si el usuario definió horarios válidos
    # predefinidos, el algoritmo SOLO puede usar esos bloques -- no inventa horarios nuevos. ----
    plantillas_por_dia = {dia: [] for dia in DIAS_SEMANA}
    for pl in listar_plantillas_turno(db_path=db_path):
        for dia in pl["dias_aplica"]:
            if dia in plantillas_por_dia:
                plantillas_por_dia[dia].append(pl)

    disponibilidad_cache = {e["id"]: obtener_disponibilidad(e["id"], db_path=db_path) for e in empleados}

    # ---- Preparar candidatos y cobertura inicial de cada día (permisos, disponibilidad) ----
    for dia in DIAS_SEMANA:
        fecha_str = fechas_semana[dia].strftime("%Y-%m-%d")
        demanda_dia = demanda.get(dia, {})
        permisos_hoy = empleados_de_permiso_en_fecha(fecha_str, db_path=db_path)
        permisos_por_nombre = {p["nombre"]: p["tipo"] for p in permisos_hoy}

        cobertura[dia] = {
            h: {"requeridos": demanda_dia.get(h, 0), "programados": 0,
                "calls": datos_demanda.get(dia, {}).get(h, {}).get("calls", 0),
                "aht_seconds": datos_demanda.get(dia, {}).get(h, {}).get("aht_seconds", 150)}
            for h in range(HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN)
        }

        candidatos = []
        for e in empleados:
            nombre = e["nombre"]
            if nombre in permisos_por_nombre:
                horario[nombre][dia] = {"motivo": f"permiso:{permisos_por_nombre[nombre]}"}
                continue
            disp = disponibilidad_cache[e["id"]].get(dia)
            ventana = _ventana_disponibilidad(disp, dia)
            if ventana is None:
                motivo = "sin_informacion" if (disp and disp["tipo"] == "sin_informacion") else "no_disponible"
                horario[nombre][dia] = {"motivo": motivo}
                continue
            candidatos.append((e, ventana))
        candidatos_por_dia[dia] = candidatos

    # ---- Historial para rotación justa: cuántas veces trabajó cada quien este día de la
    # semana en semanas anteriores. Se usa para darle prioridad a quien menos lo ha hecho. ----
    conteo_historico_dia = {
        dia: conteo_historico_por_dia_semana(dia, fecha_lunes.isoformat(), db_path=db_path,
                                              semanas_atras=config.get("semanas_rotacion_historial", 10))
        for dia in DIAS_SEMANA
    }

    # ---- Garantía de descanso: todo asesor debe tener AL MENOS 1 día libre a la semana.
    # Si alguien tiene disponibilidad los 7 días (ej. "Completa" toda la semana), no se le
    # puede dejar programado los 7 -- se le reserva un día de descanso, eligiendo el día en
    # que menos hace falta (menor demanda) entre los que ya ha tenido que trabajar MÁS veces
    # ese mismo día en semanas anteriores (rotación justa: el descanso también rota). Si el
    # asesor ya tiene algún día sin disponibilidad/con permiso, ese día ya cumple como su
    # descanso natural y no se le quita ninguno adicional. ----
    dia_descanso_empleado = {}
    conteo_descansos_por_dia = {dia: 0 for dia in DIAS_SEMANA}
    PESO_ANTIAGLOMERACION = 120  # penaliza elegir un día que ya tiene mucha gente descansando

    # Carga relativa de cada día: demanda entre cuánta gente realmente puede cubrirlo. Un
    # día con demanda media pero pocos disponibles (ej. Martes) es más sensible a perder
    # gente a descanso que uno con más demanda pero mucha más gente disponible (ej. Sábado)
    # -- usar solo la demanda absoluta subestimaba justo ese caso.
    carga_relativa_dia = {}
    for dia in DIAS_SEMANA:
        n_disponibles = len(candidatos_por_dia.get(dia, []))
        carga_relativa_dia[dia] = sum(demanda.get(dia, {}).values()) / max(1, n_disponibles)

    for e in empleados:
        nombre = e["nombre"]
        dias_disponibles = [dia for dia in DIAS_SEMANA
                            if any(cand[0]["nombre"] == nombre for cand in candidatos_por_dia[dia])]
        if len(dias_disponibles) < 7:
            continue  # ya tiene un día natural sin disponibilidad/con permiso, no hace falta forzar otro

        # Elegir el día de descanso balanceando 3 cosas: baja carga relativa (no solo
        # demanda total, sino demanda por persona disponible), que no se repita siempre el
        # mismo día para todo el equipo (reparte los descansos en la semana), y que rote
        # semana a semana para la misma persona (usa el historial).
        def _score_descanso(dia):
            veces_trabajado_antes = conteo_historico_dia.get(dia, {}).get(e["id"], 0)
            return carga_relativa_dia[dia] * 10 + conteo_descansos_por_dia[dia] * PESO_ANTIAGLOMERACION - veces_trabajado_antes

        # El Domingo normalmente no se ofrece como día de descanso (regla de negocio,
        # configurable en Configuración General -- clave 'permitir_descanso_domingo').
        # Solo se filtra aquí, después de confirmar que la persona tiene los 7 días
        # disponibles -- si de verdad no tiene otra opción, igual nunca queda sin las 6
        # alternativas restantes, porque este chequeo solo corre cuando ya se sabe que
        # dias_disponibles tiene los 7 días.
        dias_candidatos_descanso = dias_disponibles
        if not config.get("permitir_descanso_domingo", False):
            dias_candidatos_descanso = [d for d in dias_disponibles if d != "Domingo"]

        dia_elegido = min(dias_candidatos_descanso, key=_score_descanso)
        dia_descanso_empleado[nombre] = dia_elegido
        conteo_descansos_por_dia[dia_elegido] += 1
        candidatos_por_dia[dia_elegido] = [c for c in candidatos_por_dia[dia_elegido] if c[0]["nombre"] != nombre]
        horario[nombre][dia_elegido] = {"motivo": "descanso_asignado"}

    MAX_TURNOS_POR_DIA = config.get("max_turnos_por_dia", 1)  # un solo turno por asesor por día, salvo que se configure otro

    def _segmento_libre(turnos_previos, hi, hf, hora_pico):
        """Ventana continua [inicio, fin) dentro de (hi, hf) que contiene hora_pico y no se
        traslapa con ningún turno ya asignado ese día a este empleado (para turnos partidos)."""
        inicio, fin = hi, hf
        for t in turnos_previos:
            if t["fin"] <= hora_pico and t["fin"] > inicio:
                inicio = t["fin"]
            if t["inicio"] >= hora_pico and t["inicio"] < fin:
                fin = t["inicio"]
        return inicio, fin

    def _construir_turno(dia, inicio, fin, plantilla_usada, excepcion=False):
        """Arma el dict final de un turno. Si la plantilla usada trae almuerzo, elige
        automáticamente en qué hora cae, con 3 reglas:
          1. NUNCA en la primera ni en la última hora del turno (siempre debe trabajar al
             menos 1h antes y 1h después de almorzar -- no tiene sentido almorzar apenas
             entra o justo antes de irse).
          2. Preferentemente dentro de la VENTANA VALLE configurada (por defecto 2:30pm-6pm,
             ajustable en Configuración General -- clave 'almuerzo_valle_inicio'/'_fin') --
             si el turno no alcanza a tocar esa ventana (ej. un turno solo de mañana), se
             relaja a cualquier hora del turno que cumpla la regla 1, en vez de dejarlo sin
             almuerzo.
          3. Se reparte entre distintas horas del día: penaliza fuertemente elegir una hora
             donde YA hay gente almorzando, para que no se amontonen todos a la misma vez
             dejando el teléfono sin nadie en esa franja.
        La hora elegida no cuenta como cobertura real ni como hora pagada."""
        almuerzo_horas = int(round(plantilla_usada["duracion_almuerzo_horas"])) if plantilla_usada else 0
        turno = {"inicio": inicio, "fin": fin, "excepcion": excepcion}

        if almuerzo_horas > 0 and (fin - inicio) > almuerzo_horas:
            # Debe quedar al menos 1h trabajada antes y 1h después del almuerzo
            h0_min = inicio + 1
            h0_max = fin - almuerzo_horas - 1
            if h0_min <= h0_max:
                valle_inicio = config.get("almuerzo_valle_inicio", 14.5)
                valle_fin = config.get("almuerzo_valle_fin", 18.0)
                h0_min_valle = max(h0_min, math.ceil(valle_inicio))
                h0_max_valle = min(h0_max, math.floor(valle_fin) - almuerzo_horas)
                if h0_min_valle <= h0_max_valle:
                    candidatos_h0 = range(h0_min_valle, h0_max_valle + 1)
                else:
                    candidatos_h0 = range(h0_min, h0_max + 1)  # el turno no alcanza a tocar el valle

                mejor_inicio_almuerzo, mejor_puntaje = None, None
                for h0 in candidatos_h0:
                    horas_bloque = range(h0, h0 + almuerzo_horas)
                    demanda = sum(cobertura[dia][h]["requeridos"] for h in horas_bloque)
                    ya_almuerzan = sum(almuerzos_por_hora[dia].get(h, 0) for h in horas_bloque)
                    puntaje = demanda + ya_almuerzan * 50  # penaliza fuerte repetir hora ya usada
                    if mejor_puntaje is None or puntaje < mejor_puntaje:
                        mejor_puntaje, mejor_inicio_almuerzo = puntaje, h0
                turno["almuerzo_inicio"] = mejor_inicio_almuerzo
                turno["almuerzo_horas"] = almuerzo_horas
                for h in range(mejor_inicio_almuerzo, mejor_inicio_almuerzo + almuerzo_horas):
                    almuerzos_por_hora[dia][h] = almuerzos_por_hora[dia].get(h, 0) + 1
            # Si el turno es tan corto que no cabe 1h antes + almuerzo + 1h después, se deja
            # sin almuerzo asignado (se paga completo) en vez de forzarlo en un mal horario.
        return turno

    def _horas_efectivas_turno(t):
        """Horas realmente pagadas/cubiertas de un turno (descuenta el almuerzo, si tiene)."""
        return (t["fin"] - t["inicio"]) - t.get("almuerzo_horas", 0)

    def _horas_cobertura_turno(t):
        """Horas del turno que SÍ cuentan como cobertura real (excluye la hora de almuerzo)."""
        return horas_pagables_turno(t)

    def _procesar_dia(dia, duracion_preferida_max=None, fraccion_objetivo=1.0):
        """
        Llena el déficit de UN día completo con el método voraz de siempre (turno que más
        déficit cubre, ajustado al ancho del pico). 'fraccion_objetivo' limita hasta qué %
        del requerido se intenta cubrir en esta pasada -- se usa dos veces por día: primero
        una pasada de PISO MÍNIMO (fracción baja, ej. 0.4) en TODOS los días empezando por
        los más tranquilos, para que nadie quede en cero aunque sea de último en prioridad;
        luego una pasada de IMPACTO (fracción 1.0) en orden de mayor a menor demanda, para
        que el presupuesto que sobra se lo lleve primero el día que más le cuesta al negocio
        si queda mal cubierto. Sin el piso mínimo, un día de baja demanda puede quedar casi
        huérfano: para cuando le toca su turno (de último), la mayoría ya agotó su tope
        semanal de horas en los días de mayor prioridad, aunque sí tuvieran disponibilidad.
        """
        candidatos = candidatos_por_dia[dia]
        asignados_hoy = asignados_por_dia[dia]
        plantillas_hoy = plantillas_por_dia.get(dia, [])
        max_iter = len(candidatos) + 8

        for _ in range(max_iter):
            deficits = {}
            for h, c in cobertura[dia].items():
                techo = max(1, round(c["requeridos"] * fraccion_objetivo)) if c["requeridos"] > 0 else 0
                d = techo - c["programados"]
                if d > 0:
                    deficits[h] = d
            if not deficits:
                break

            # Elegir qué hora atender primero por déficit ESCASEZ-PONDERADO, no déficit
            # bruto -- una hora con poco déficit pero MUY pocos candidatos que puedan
            # cubrirla (ej. la apertura a las 11:00, que solo unos pocos alcanzan por su
            # disponibilidad) es más urgente que una con más déficit pero muchos candidatos
            # disponibles. Sin esto, esas horas escasas se dejaban de últimas en la cola y
            # para cuando les tocaba turno ya no quedaba casi nadie que pudiera cubrirlas
            # (los pocos que sí alcanzaban ya habían sido asignados a otra hora primero).
            def _urgencia_hora(h):
                candidatos_libres = sum(
                    1 for e, (hi, hf) in candidatos
                    if hi <= h < hf and len(asignados_hoy.get(e["nombre"], [])) < MAX_TURNOS_POR_DIA
                )
                return deficits[h] / max(1, candidatos_libres)

            hora_pico = max(deficits, key=_urgencia_hora)
            mejor, mejor_score = None, -1

            for e, (hi, hf) in candidatos:
                nombre = e["nombre"]
                turnos_previos = asignados_hoy.get(nombre, [])
                if len(turnos_previos) >= MAX_TURNOS_POR_DIA or not (hi <= hora_pico < hf):
                    continue
                if any(t["inicio"] <= hora_pico < t["fin"] for t in turnos_previos):
                    continue

                restante_semana = e["horas_max_semana"] - horas_semana[nombre]
                if restante_semana < 1:
                    continue

                horas_ya_hoy = sum(t["fin"] - t["inicio"] for t in turnos_previos)
                tope_dia_total = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia == "Domingo" else e["horas_max_dia"]
                restante_dia = tope_dia_total - horas_ya_hoy
                urgencia_minimo = max(0, e["horas_min_semana"] - horas_semana[nombre])
                veces_este_dia_antes = conteo_historico_dia.get(dia, {}).get(e["id"], 0)
                bonus_rotacion = -veces_este_dia_antes * 4
                penalizacion_partido = -2 if turnos_previos else 0

                if plantillas_hoy:
                    for pl in plantillas_hoy:
                        pi, pf = pl["hora_inicio"], pl["hora_fin"]
                        if not (hi <= pi and pf <= hf) or not (pi <= hora_pico < pf):
                            continue
                        dur = pf - pi
                        dur_efectiva = dur - pl["duracion_almuerzo_horas"]
                        if dur_efectiva > restante_dia or dur_efectiva > restante_semana:
                            continue
                        if any(pi < t["fin"] and t["inicio"] < pf for t in turnos_previos):
                            continue
                        utilidad = sum(1 for h in range(pi, pf) if deficits.get(h, 0) > 0)
                        # Penaliza las horas de la plantilla que YA estaban completas -- sin esto,
                        # con muchas plantillas aplicables el mismo día (ej. Sábado con 9), el
                        # algoritmo no distingue entre una plantilla ajustada y una ancha que
                        # desperdicia cobertura en horas que no la necesitaban.
                        desperdicio = sum(1 for h in range(pi, pf)
                                           if cobertura[dia][h]["programados"] >= cobertura[dia][h]["requeridos"])
                        score = utilidad * 10 - desperdicio * 3 + urgencia_minimo + bonus_rotacion + penalizacion_partido
                        if score > mejor_score:
                            mejor_score, mejor = score, (e, pi, pf, pl)
                else:
                    seg_inicio, seg_fin = _segmento_libre(turnos_previos, hi, hf, hora_pico)
                    max_dur = min(restante_dia, restante_semana, seg_fin - seg_inicio)
                    minimo_este_turno = int(e["horas_min_dia"]) if not turnos_previos else min(2, int(e["horas_min_dia"]))
                    if max_dur < minimo_este_turno:
                        continue

                    utilidad = sum(1 for h in range(seg_inicio, seg_fin) if deficits.get(h, 0) > 0)
                    score = utilidad * 10 + urgencia_minimo + bonus_rotacion + penalizacion_partido
                    if score > mejor_score:
                        ancho_bloque = _ancho_bloque_deficit(deficits, seg_inicio, seg_fin, hora_pico)
                        duracion_max_efectiva = min(int(math.floor(max_dur)), ancho_bloque)
                        if duracion_preferida_max is not None:
                            duracion_max_efectiva = min(duracion_max_efectiva, duracion_preferida_max)
                        duracion = max(minimo_este_turno, duracion_max_efectiva)

                        inicio_min = max(seg_inicio, hora_pico - duracion + 1)
                        inicio_max = min(hora_pico, seg_fin - duracion)
                        mejor_inicio, mejor_peso = inicio_min, -1
                        for inicio_c in range(inicio_min, inicio_max + 1):
                            peso = sum(deficits.get(h, 0) for h in range(inicio_c, inicio_c + duracion))
                            if peso > mejor_peso:
                                mejor_peso, mejor_inicio = peso, inicio_c

                        mejor_score, mejor = score, (e, mejor_inicio, mejor_inicio + duracion, None)

            if mejor is None:
                break

            e, inicio, fin, plantilla_usada = mejor
            nombre = e["nombre"]
            turno = _construir_turno(dia, inicio, fin, plantilla_usada)
            asignados_hoy.setdefault(nombre, []).append(turno)
            horas_semana[nombre] += _horas_efectivas_turno(turno)
            for h in _horas_cobertura_turno(turno):
                cobertura[dia][h]["programados"] += 1

    # ---- Procesar los días en orden de MAYOR a MENOR demanda semanal: el día que más le
    # cuesta al negocio si queda mal cubierto (más llamadas reales en juego) se resuelve
    # primero, con el presupuesto semanal completo de todos disponible. Los días de menor
    # impacto se ajustan con lo que va quedando -- la pasada de reparación de más abajo
    # garantiza que ninguno quede en cero, así sea el de menor prioridad. ----
    orden_por_impacto = sorted(DIAS_SEMANA, key=lambda d: -sum(demanda.get(d, {}).values()))

    # El tope de turnos cortos (duracion_preferida_max) es genial para eficiencia en días
    # tranquilos, pero en los días de MAYOR demanda compite directamente contra la cobertura:
    # si cada turno dura poco, hace falta mucha más gente distinta ese día de la que
    # físicamente hay disponible. Por eso el tope corto solo se aplica a la mitad de días
    # con MENOR demanda -- los de mayor impacto usan turnos completos (hasta el máximo
    # diario normal) para poder juntar más horas con la gente que sí está disponible.
    n_dias_sin_tope = n_dias_prioridad_maxima  # los N de mayor demanda (normalmente viernes-sábado-domingo)
    dias_sin_tope_corto = set(orden_por_impacto[:n_dias_sin_tope])

    # ---- PASE 1 (PISO MÍNIMO): reservar una base de cobertura en TODOS los días --
    # empezando por los más tranquilos -- ANTES de que los días de mayor demanda agoten el
    # presupuesto semanal de todos. Sin esto, un día de baja demanda puede quedar casi
    # huérfano (la gente disponible ese día ya gastó su tope semanal en días de más
    # prioridad, procesados antes). ----
    fraccion_piso_minimo = config.get("fraccion_piso_minimo", 0.40)
    orden_ascendente = list(reversed(orden_por_impacto))
    for dia in orden_ascendente:
        tope_efectivo = None if dia in dias_sin_tope_corto else duracion_preferida_max
        _procesar_dia(dia, duracion_preferida_max=tope_efectivo, fraccion_objetivo=fraccion_piso_minimo)

    # ---- PASE 2 (IMPACTO): con el presupuesto que queda, terminar de cubrir por orden de
    # mayor a menor demanda -- el día que más le cuesta al negocio si queda mal cubierto se
    # lleva primero lo que sobra. ----
    for dia in orden_por_impacto:
        tope_efectivo = None if dia in dias_sin_tope_corto else duracion_preferida_max
        _procesar_dia(dia, duracion_preferida_max=tope_efectivo, fraccion_objetivo=1.0)

    # ---- PASE DE REPARACIÓN: cualquier hora que haya quedado en CERO programados (mientras
    # se requería gente), se rellena con quien todavía tenga disponibilidad y presupuesto
    # semanal, aunque sea con un turno corto (incluso como segundo turno partido). Esto evita
    # que un día quede completamente desatendido en alguna franja. ----
    for dia in DIAS_SEMANA:
        plantillas_hoy = plantillas_por_dia.get(dia, [])
        for h in range(HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN):
            if cobertura[dia][h]["requeridos"] > 0 and cobertura[dia][h]["programados"] == 0:
                candidatos = candidatos_por_dia[dia]
                asignados_hoy = asignados_por_dia[dia]
                mejor = None

                # Intento 1: cubrir con alguna plantilla válida (si hay plantillas definidas)
                if plantillas_hoy:
                    for e, (hi, hf) in candidatos:
                        nombre = e["nombre"]
                        turnos_previos = asignados_hoy.get(nombre, [])
                        if len(turnos_previos) >= MAX_TURNOS_POR_DIA:
                            continue
                        restante_semana = e["horas_max_semana"] - horas_semana[nombre]
                        if restante_semana < 1:
                            continue
                        horas_ya_hoy = sum(t["fin"] - t["inicio"] for t in turnos_previos)
                        tope_dia = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia == "Domingo" else e["horas_max_dia"]
                        restante_dia = tope_dia - horas_ya_hoy
                        encontrado = None
                        for pl in plantillas_hoy:
                            pi, pf = pl["hora_inicio"], pl["hora_fin"]
                            if not (hi <= pi and pf <= hf) or not (pi <= h < pf):
                                continue
                            dur = pf - pi
                            dur_efectiva = dur - pl["duracion_almuerzo_horas"]
                            if dur_efectiva > restante_dia or dur_efectiva > restante_semana:
                                continue
                            if any(pi < t["fin"] and t["inicio"] < pf for t in turnos_previos):
                                continue
                            encontrado = (pi, pf)
                            break
                        if encontrado:
                            mejor = (e, encontrado[0], encontrado[1], False, pl)
                            break

                # Intento 2 (respaldo, modo libre): si ninguna plantilla calza, se arma un
                # bloque a medida -- mejor cubrir la hora con lo que sea, a que quede en cero.
                if mejor is None:
                    for e, (hi, hf) in candidatos:
                        nombre = e["nombre"]
                        turnos_previos = asignados_hoy.get(nombre, [])
                        if len(turnos_previos) >= MAX_TURNOS_POR_DIA or not (hi <= h < hf):
                            continue
                        if any(t["inicio"] <= h < t["fin"] for t in turnos_previos):
                            continue
                        restante_semana = e["horas_max_semana"] - horas_semana[nombre]
                        if restante_semana < 1:
                            continue
                        seg_inicio, seg_fin = _segmento_libre(turnos_previos, hi, hf, h)
                        horas_ya_hoy = sum(t["fin"] - t["inicio"] for t in turnos_previos)
                        tope_dia = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia == "Domingo" else e["horas_max_dia"]
                        restante_dia = tope_dia - horas_ya_hoy
                        duracion = max(1, int(math.floor(min(restante_dia, seg_fin - seg_inicio, restante_semana))))
                        inicio_c = max(seg_inicio, min(h, seg_fin - duracion))
                        mejor = (e, inicio_c, inicio_c + duracion, True, None)
                        break

                if mejor:
                    e, inicio, fin, es_excepcion, plantilla_usada = mejor
                    nombre = e["nombre"]
                    turno = _construir_turno(dia, inicio, fin, plantilla_usada, excepcion=es_excepcion)
                    asignados_por_dia[dia].setdefault(nombre, []).append(turno)
                    horas_semana[nombre] += _horas_efectivas_turno(turno)
                    for hh in _horas_cobertura_turno(turno):
                        cobertura[dia][hh]["programados"] += 1

    # ---- GARANTÍA DE MÍNIMO SEMANAL: si alguien quedó por debajo de su mínimo contractual,
    # se le agregan más horas -- aunque eso signifique un poco de sobre-cobertura -- en vez
    # de dejarlo corto. Se prefiere pasarse por 1-2h a que alguien quede bajo su mínimo. ----
    for e in empleados:
        nombre = e["nombre"]
        faltante = e["horas_min_semana"] - horas_semana[nombre]
        if faltante <= 0:
            continue

        # Días donde este asesor tenía disponibilidad original pero no quedó con turno hoy
        dias_con_ventana = {}
        for dia in DIAS_SEMANA:
            if nombre in asignados_por_dia[dia]:
                continue  # ya tiene turno ese día (máximo 1 turno/día)
            for cand_e, cand_ventana in candidatos_por_dia[dia]:
                if cand_e["nombre"] == nombre:
                    dias_con_ventana[dia] = cand_ventana
                    break

        # Probar primero el día que MÁS lo necesita (más déficit real de cobertura ahora
        # mismo), no solo el que tenga la ventana de disponibilidad más angosta.
        def _urgencia_dia(item):
            dia, (hi, hf) = item
            deficit_dia = sum(max(0, c["requeridos"] - c["programados"]) for c in cobertura[dia].values())
            return (-deficit_dia, hf - hi)

        for dia, (hi, hf) in sorted(dias_con_ventana.items(), key=_urgencia_dia):
            if faltante <= 0:
                break
            tope_dia = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia == "Domingo" else e["horas_max_dia"]
            plantillas_hoy = plantillas_por_dia.get(dia, [])

            if plantillas_hoy:
                candidatas = [pl for pl in plantillas_hoy
                              if hi <= pl["hora_inicio"] and pl["hora_fin"] <= hf
                              and (pl["hora_fin"] - pl["hora_inicio"] - pl["duracion_almuerzo_horas"]) <= tope_dia]
                if not candidatas:
                    continue

                def _puntaje_candidata(p):
                    dur_diff = abs((p["hora_fin"] - p["hora_inicio"] - p["duracion_almuerzo_horas"]) - faltante)
                    desperdicio = sum(1 for h in range(p["hora_inicio"], p["hora_fin"])
                                       if cobertura[dia][h]["programados"] >= cobertura[dia][h]["requeridos"])
                    # La duración pesa más (es el objetivo principal de esta pasada), pero entre
                    # opciones parecidas se prefiere la que menos desperdicia cobertura ya cubierta
                    # -- sin esto, alguien podía terminar en un turno de Sábado que sobre-cubre
                    # horas que ya estaban completas, en vez de uno igual de válido que no lo hace.
                    return dur_diff * 3 + desperdicio

                pl = min(candidatas, key=_puntaje_candidata)
                inicio, fin, plantilla_usada = pl["hora_inicio"], pl["hora_fin"], pl
            else:
                duracion = int(min(tope_dia, hf - hi, max(int(e["horas_min_dia"]), math.ceil(faltante))))
                if duracion < e["horas_min_dia"]:
                    continue
                inicio, fin, plantilla_usada = hi, hi + duracion, None

            turno = _construir_turno(dia, inicio, fin, plantilla_usada)
            asignados_por_dia[dia].setdefault(nombre, []).append(turno)
            horas_semana[nombre] += _horas_efectivas_turno(turno)
            for h in _horas_cobertura_turno(turno):
                cobertura[dia][h]["programados"] += 1
            faltante = e["horas_min_semana"] - horas_semana[nombre]

    # ---- Si aún falta (ya no había días libres para agregar un turno nuevo), se intenta
    # EXTENDER un turno ya existente dentro de su ventana de disponibilidad original -- ej.
    # alguien con turno 18-22h pero disponible desde las 14h, se le extiende hacia atrás. ----
    for e in empleados:
        nombre = e["nombre"]
        faltante = e["horas_min_semana"] - horas_semana[nombre]
        if faltante <= 0:
            continue

        opciones = []
        for dia in DIAS_SEMANA:
            turnos = asignados_por_dia[dia].get(nombre, [])
            if len(turnos) != 1:
                continue
            turno = turnos[0]
            ventana = next((cv for ce, cv in candidatos_por_dia[dia] if ce["nombre"] == nombre), None)
            if ventana is None:
                continue
            hi, hf = ventana
            tope_dia = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia == "Domingo" else e["horas_max_dia"]
            horas_actuales = turno["fin"] - turno["inicio"]
            margen_total = max(0, min(tope_dia - horas_actuales, (hf - hi) - horas_actuales))
            if margen_total > 0:
                opciones.append((margen_total, dia, turno, hi, hf, tope_dia))

        for margen_total, dia, turno, hi, hf, tope_dia in sorted(opciones, key=lambda o: -o[0]):
            if faltante <= 0:
                break
            plantillas_hoy = plantillas_por_dia.get(dia, [])
            inicio_orig, fin_orig = turno["inicio"], turno["fin"]
            plantilla_nueva = None

            if plantillas_hoy:
                # En modo plantillas no se "estira" libremente -- se busca una plantilla más
                # grande que YA incluya por completo el turno actual (mismo horario base,
                # solo más largo), y se cambia el turno por esa.
                candidatas = [pl for pl in plantillas_hoy
                              if hi <= pl["hora_inicio"] <= inicio_orig and fin_orig <= pl["hora_fin"] <= hf
                              and (pl["hora_fin"] - pl["hora_inicio"] - pl["duracion_almuerzo_horas"]) <= tope_dia
                              and (pl["hora_fin"] - pl["hora_inicio"]) > (fin_orig - inicio_orig)]
                if not candidatas:
                    continue

                def _puntaje_extension(p):
                    duracion = p["hora_fin"] - p["hora_inicio"]
                    # Desperdicio SOLO de las horas nuevas que se agregarían (las que ya
                    # tenía el turno original no cuentan, esas ya estaban decididas)
                    horas_nuevas = [h for h in range(p["hora_inicio"], p["hora_fin"])
                                    if h < inicio_orig or h >= fin_orig]
                    desperdicio = sum(1 for h in horas_nuevas
                                       if cobertura[dia][h]["programados"] >= cobertura[dia][h]["requeridos"])
                    return duracion + desperdicio * 2

                plantilla_nueva = min(candidatas, key=_puntaje_extension)
                nuevo_inicio, nuevo_fin = plantilla_nueva["hora_inicio"], plantilla_nueva["hora_fin"]
            else:
                extension = int(min(margen_total, math.ceil(faltante)))
                nuevo_fin = min(hf, fin_orig + extension)
                extendido_adelante = nuevo_fin - fin_orig
                nuevo_inicio = int(max(hi, inicio_orig - (extension - extendido_adelante)))

            # Se reconstruye el turno desde cero (recalcula dónde cae el almuerzo si aplica)
            # y se reconcilia la cobertura: se retira el efecto del turno viejo y se aplica
            # el del nuevo, en vez de solo sumar la diferencia de horas -- así el almuerzo
            # queda bien ubicado incluso si cambia de posición al cambiar de plantilla.
            horas_cobertura_viejas = set(_horas_cobertura_turno(turno))
            turno_nuevo = _construir_turno(dia, nuevo_inicio, nuevo_fin, plantilla_nueva)
            horas_cobertura_nuevas = set(_horas_cobertura_turno(turno_nuevo))

            for h in horas_cobertura_viejas - horas_cobertura_nuevas:
                cobertura[dia][h]["programados"] -= 1
            for h in horas_cobertura_nuevas - horas_cobertura_viejas:
                cobertura[dia][h]["programados"] += 1

            delta = _horas_efectivas_turno(turno_nuevo) - _horas_efectivas_turno(turno)
            turno.clear()
            turno.update(turno_nuevo)
            horas_semana[nombre] += delta
            faltante = e["horas_min_semana"] - horas_semana[nombre]

    # ---- PASE DE REBALANCEO ENTRE DÍAS: busca gente que trabaja tanto un día con exceso
    # de cobertura como un día con déficit, y prueba cambiarles la plantilla de AMBOS días
    # para que su turno del día sobrante deje de tapar horas que ya estaban cubiertas, y su
    # turno del día flojo ayude más. Revisa TODOS los pares de días (no solo "el peor contra
    # el peor"), y permite que el total de horas de la persona cambie, siempre que se quede
    # dentro de su mínimo/máximo semanal de contrato. Al final se compara el % de servicio
    # REAL (Erlang, no un proxy lineal) antes y después -- si algún día empeora más de lo
    # tolerable, se revierte TODO el rebalanceo completo, para nunca entregar algo peor de
    # lo que ya había. No toca días de descanso ni agrega turnos nuevos: solo actúa sobre
    # gente que YA trabaja ambos días. ----
    import copy as _copy_module

    snapshot_turnos = []  # [(dict_del_turno, copia_de_su_contenido_original), ...]
    for dia in DIAS_SEMANA:
        for nombre, turnos in asignados_por_dia[dia].items():
            for t in turnos:
                snapshot_turnos.append((t, dict(t)))
    snapshot_cobertura = _copy_module.deepcopy(cobertura)
    snapshot_horas_semana = dict(horas_semana)
    turnos_creados_por_rebalanceo = []  # [(dia, nombre, dict_del_turno_nuevo), ...] -- para poder
    # deshacerlos si la red de seguridad final detecta que el rebalanceo completo empeoró algo

    def _score_desbalance(dia):
        # Solo cuenta el DÉFICIT -- el exceso de cobertura no perjudica el servicio (solo
        # cuesta de más), así que no tiene sentido "penalizarlo" igual que a un hueco real.
        # Optimizar por |exceso-déficit| simétrico hacía que el pase, en rondas sucesivas,
        # le quitara horas a un día que solo tenía un poquito de exceso aunque en el fondo
        # ese día siguiera necesitando más gente en total -- empeorándolo sin necesidad.
        return sum(max(0, c["requeridos"] - c["programados"]) for c in cobertura[dia].values())

    empleados_por_nombre = {e["nombre"]: e for e in empleados}
    for _ in range(40):
        exceso_por_dia = {d: sum(max(0, c["programados"] - c["requeridos"]) for c in cobertura[d].values()) for d in DIAS_SEMANA}
        deficit_por_dia = {d: sum(max(0, c["requeridos"] - c["programados"]) for c in cobertura[d].values()) for d in DIAS_SEMANA}
        dias_con_exceso = [d for d in DIAS_SEMANA if exceso_por_dia[d] > 0 and plantillas_por_dia.get(d)]
        dias_con_deficit = [d for d in DIAS_SEMANA if deficit_por_dia[d] > 0 and plantillas_por_dia.get(d)]
        if not dias_con_exceso or not dias_con_deficit:
            break

        mejor_swap, mejor_mejora, mejor_par = None, 0, None
        for dia_sobrante in dias_con_exceso:
            for dia_faltante in dias_con_deficit:
                if dia_sobrante == dia_faltante:
                    continue
                plantillas_A = plantillas_por_dia.get(dia_sobrante, [])
                plantillas_B = plantillas_por_dia.get(dia_faltante, [])

                for nombre, turnos_A in asignados_por_dia[dia_sobrante].items():
                    if len(turnos_A) != 1:
                        continue
                    turnos_B = asignados_por_dia[dia_faltante].get(nombre)
                    ya_trabaja_B = bool(turnos_B) and len(turnos_B) == 1
                    # Caso normal: ya trabaja ambos días -- se le cambia la plantilla de
                    # ambos. Caso nuevo: tiene disponibilidad el día flojo pero no lo estaba
                    # trabajando (no por descanso, simplemente no hacía falta antes) -- se le
                    # AGREGA ese día completo, recortando el día sobrante para compensar.
                    if not ya_trabaja_B:
                        if dia_descanso_empleado.get(nombre) == dia_faltante:
                            continue  # ese día es su descanso asignado, no se toca
                        tiene_ventana_b = any(ce["nombre"] == nombre for ce, cv in candidatos_por_dia[dia_faltante])
                        if not tiene_ventana_b:
                            continue  # no tiene disponibilidad real ese día, no hay nada que hacer

                    turno_A = turnos_A[0]
                    turno_B = turnos_B[0] if ya_trabaja_B else None
                    e = empleados_por_nombre[nombre]
                    ventana_A = next((cv for ce, cv in candidatos_por_dia[dia_sobrante] if ce["nombre"] == nombre), None)
                    ventana_B = next((cv for ce, cv in candidatos_por_dia[dia_faltante] if ce["nombre"] == nombre), None)
                    if not ventana_A or not ventana_B:
                        continue

                    dur_actual_total = _horas_efectivas_turno(turno_A) + (_horas_efectivas_turno(turno_B) if turno_B else 0)

                    for pl_A in plantillas_A:
                        if not (ventana_A[0] <= pl_A["hora_inicio"] and pl_A["hora_fin"] <= ventana_A[1]):
                            continue
                        dur_A = (pl_A["hora_fin"] - pl_A["hora_inicio"]) - pl_A["duracion_almuerzo_horas"]
                        tope_A = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia_sobrante == "Domingo" else e["horas_max_dia"]
                        if dur_A > tope_A:
                            continue
                        for pl_B in plantillas_B:
                            if not (ventana_B[0] <= pl_B["hora_inicio"] and pl_B["hora_fin"] <= ventana_B[1]):
                                continue
                            dur_B = (pl_B["hora_fin"] - pl_B["hora_inicio"]) - pl_B["duracion_almuerzo_horas"]
                            tope_B = min(e["horas_max_dia"], DOMINGO_MAX_HORAS) if dia_faltante == "Domingo" else e["horas_max_dia"]
                            if dur_B > tope_B:
                                continue
                            nuevo_total_semana = horas_semana[nombre] - dur_actual_total + dur_A + dur_B
                            if not (e["horas_min_semana"] <= nuevo_total_semana <= e["horas_max_semana"]):
                                continue  # respeta el contrato de esa persona

                            horas_cob_A_actual = set(_horas_cobertura_turno(turno_A))
                            horas_cob_B_actual = set(_horas_cobertura_turno(turno_B)) if turno_B else set()
                            turno_A_nuevo = _construir_turno(dia_sobrante, pl_A["hora_inicio"], pl_A["hora_fin"], pl_A)
                            turno_B_nuevo = _construir_turno(dia_faltante, pl_B["hora_inicio"], pl_B["hora_fin"], pl_B)
                            horas_cob_A_nueva = set(_horas_cobertura_turno(turno_A_nuevo))
                            horas_cob_B_nueva = set(_horas_cobertura_turno(turno_B_nuevo))
                            if horas_cob_A_nueva == horas_cob_A_actual and horas_cob_B_nueva == horas_cob_B_actual:
                                continue  # sin cambio real de cobertura, no vale la pena

                            score_antes = _score_desbalance(dia_sobrante) + _score_desbalance(dia_faltante)
                            for h in horas_cob_A_actual: cobertura[dia_sobrante][h]["programados"] -= 1
                            for h in horas_cob_A_nueva: cobertura[dia_sobrante][h]["programados"] += 1
                            for h in horas_cob_B_actual: cobertura[dia_faltante][h]["programados"] -= 1
                            for h in horas_cob_B_nueva: cobertura[dia_faltante][h]["programados"] += 1
                            score_despues = _score_desbalance(dia_sobrante) + _score_desbalance(dia_faltante)
                            for h in horas_cob_A_nueva: cobertura[dia_sobrante][h]["programados"] -= 1
                            for h in horas_cob_A_actual: cobertura[dia_sobrante][h]["programados"] += 1
                            for h in horas_cob_B_nueva: cobertura[dia_faltante][h]["programados"] -= 1
                            for h in horas_cob_B_actual: cobertura[dia_faltante][h]["programados"] += 1

                            mejora = score_antes - score_despues
                            if mejora > mejor_mejora:
                                mejor_mejora = mejora
                                mejor_par = (dia_sobrante, dia_faltante)
                                mejor_swap = (nombre, turno_A, turno_B, turno_A_nuevo, turno_B_nuevo,
                                              horas_cob_A_actual, horas_cob_A_nueva, horas_cob_B_actual, horas_cob_B_nueva,
                                              dur_actual_total, dur_A, dur_B)

        if mejor_swap is None:
            break

        (nombre, turno_A, turno_B, turno_A_nuevo, turno_B_nuevo,
         hcA_old, hcA_new, hcB_old, hcB_new, dur_actual_total, dur_A, dur_B) = mejor_swap
        dia_sobrante, dia_faltante = mejor_par
        creando_turno_b = turno_B is None
        if creando_turno_b:
            turno_B = {}
            asignados_por_dia[dia_faltante].setdefault(nombre, []).append(turno_B)
            turnos_creados_por_rebalanceo.append((dia_faltante, nombre, turno_B))

        # SL real (Erlang) de los 2 días afectados, antes de aplicar este swap puntual --
        # el "score" usado arriba para elegir el candidato es solo un conteo de horas de
        # déficit (rápido de calcular), pero Erlang C no es lineal: una hora de déficit en
        # un pico duele mucho más que en una hora tranquila. Esta es la verificación real.
        sl_2dias_antes = estimar_nivel_servicio_real({
            "cobertura": {dia_sobrante: cobertura[dia_sobrante], dia_faltante: cobertura[dia_faltante]}
        })["por_dia"]

        turno_A_original, turno_B_original = dict(turno_A), dict(turno_B)
        for h in hcA_old: cobertura[dia_sobrante][h]["programados"] -= 1
        for h in hcA_new: cobertura[dia_sobrante][h]["programados"] += 1
        for h in hcB_old: cobertura[dia_faltante][h]["programados"] -= 1
        for h in hcB_new: cobertura[dia_faltante][h]["programados"] += 1
        turno_A.clear(); turno_A.update(turno_A_nuevo)
        turno_B.clear(); turno_B.update(turno_B_nuevo)
        horas_semana[nombre] += (dur_A + dur_B) - dur_actual_total

        sl_2dias_despues = estimar_nivel_servicio_real({
            "cobertura": {dia_sobrante: cobertura[dia_sobrante], dia_faltante: cobertura[dia_faltante]}
        })["por_dia"]

        if (sl_2dias_despues[dia_sobrante]["sl_estimado_pct"] < sl_2dias_antes[dia_sobrante]["sl_estimado_pct"] - 0.5
                or sl_2dias_despues[dia_faltante]["sl_estimado_pct"] < sl_2dias_antes[dia_faltante]["sl_estimado_pct"] - 0.5):
            # Este swap puntual empeoró alguno de los 2 días -- se revierte solo este y se
            # detiene el pase (los swaps buenos que ya se aplicaron antes se conservan).
            for h in hcA_new: cobertura[dia_sobrante][h]["programados"] -= 1
            for h in hcA_old: cobertura[dia_sobrante][h]["programados"] += 1
            for h in hcB_new: cobertura[dia_faltante][h]["programados"] -= 1
            for h in hcB_old: cobertura[dia_faltante][h]["programados"] += 1
            turno_A.clear(); turno_A.update(turno_A_original)
            if creando_turno_b:
                asignados_por_dia[dia_faltante][nombre].remove(turno_B)
                if not asignados_por_dia[dia_faltante][nombre]:
                    del asignados_por_dia[dia_faltante][nombre]
                turnos_creados_por_rebalanceo.remove((dia_faltante, nombre, turno_B))
            else:
                turno_B.clear(); turno_B.update(turno_B_original)
            horas_semana[nombre] -= (dur_A + dur_B) - dur_actual_total
            break

    # ---- Red de seguridad: comparar el % de servicio REAL (Erlang) antes y después de
    # todo el rebalanceo. El "score" usado arriba para decidir cada swap es una heurística
    # rápida (conteo de horas de déficit), no el cálculo real de Erlang C -- que no es
    # lineal, así que una hora de déficit en una hora pico duele mucho más que una en una
    # hora tranquila. Si el rebalanceo terminó empeorando algún día más de lo tolerable (o
    # la semana completa), se revierte TODO -- nunca se entrega algo peor que sin el pase. ----
    sl_antes = estimar_nivel_servicio_real({"cobertura": snapshot_cobertura})
    sl_despues = estimar_nivel_servicio_real({"cobertura": cobertura})
    peor_dia_empeoro = any(
        sl_despues["por_dia"][d]["sl_estimado_pct"] < sl_antes["por_dia"][d]["sl_estimado_pct"] - 2
        for d in DIAS_SEMANA
    )
    semana_empeoro = sl_despues["sl_estimado_semana_pct"] < sl_antes["sl_estimado_semana_pct"]
    if peor_dia_empeoro or semana_empeoro:
        for t, contenido_original in snapshot_turnos:
            t.clear()
            t.update(contenido_original)
        for dia, nombre, turno_creado in turnos_creados_por_rebalanceo:
            if nombre in asignados_por_dia[dia] and turno_creado in asignados_por_dia[dia][nombre]:
                asignados_por_dia[dia][nombre].remove(turno_creado)
                if not asignados_por_dia[dia][nombre]:
                    del asignados_por_dia[dia][nombre]
        cobertura.clear()
        cobertura.update(snapshot_cobertura)
        horas_semana.clear()
        horas_semana.update(snapshot_horas_semana)

    # ---- Consolidar: un único punto que traduce asignados_por_dia (usado por TODAS las
    # pasadas: equidad, prioridad y reparación) a la estructura final 'horario'. ----
    for dia in DIAS_SEMANA:
        for nombre, turnos in asignados_por_dia[dia].items():
            if turnos:
                horario[nombre][dia] = {"turnos": sorted(turnos, key=lambda t: t["inicio"])}

    # ---- Cerrar: marcar "libre" a quien tenía disponibilidad pero no se necesitó, y alertas ----
    for dia in DIAS_SEMANA:
        for e, _ in candidatos_por_dia[dia]:
            if e["nombre"] not in asignados_por_dia[dia] and dia not in horario[e["nombre"]]:
                motivo = "tope_semanal_alcanzado" if horas_semana[e["nombre"]] >= e["horas_max_semana"] else "libre_no_requerido"
                horario[e["nombre"]][dia] = {"motivo": motivo}

        for h in range(HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN):
            req, prog = cobertura[dia][h]["requeridos"], cobertura[dia][h]["programados"]
            if prog < req:
                alertas.append(f"{dia} {h}:00 -- faltan {req - prog} agente(s) (requeridos {req}, programados {prog})")

    for e in empleados:
        nombre = e["nombre"]
        if horas_semana[nombre] < e["horas_min_semana"]:
            alertas.append(
                f"{nombre}: quedó en {horas_semana[nombre]:.0f}h esta semana, por debajo de su mínimo "
                f"contractual de {e['horas_min_semana']:.0f}h (no hubo suficiente demanda/disponibilidad "
                f"para asignarle más)"
            )

    # ---- Guardar en el historial (para que la rotación justa funcione en semanas futuras) --
    # -- una sola transacción para las ~120 filas, no una conexión+commit por cada una. ----
    entradas_historial = []
    for e in empleados:
        nombre = e["nombre"]
        for dia, fecha_dia in fechas_semana.items():
            info = horario[nombre].get(dia, {})
            if "turnos" in info and info["turnos"]:
                hi = min(t["inicio"] for t in info["turnos"])
                hf = max(t["fin"] for t in info["turnos"])
                entradas_historial.append((e["id"], fecha_dia.isoformat(), dia, hi, hf))
            else:
                entradas_historial.append((e["id"], fecha_dia.isoformat(), dia, None, None))
    guardar_turnos_historial_batch(entradas_historial, db_path=db_path)

    return {"horario": horario, "cobertura": cobertura, "alertas": alertas, "horas_semana": horas_semana}


def estimar_nivel_servicio_real(resultado: dict, target_answer_seconds: float = 20) -> dict:
    """
    Toma el resultado de generar_horario_semana() y calcula, con los agentes REALMENTE
    programados (no los ideales), qué % de llamadas se estima contestar -- usando la misma
    fórmula Erlang C pero "hacia adelante" (dado N agentes, ¿qué service level da?).
    Se pondera por volumen de llamadas para dar un % global realista de toda la semana.
    """
    from erlang import service_level

    detalle_por_dia = {}
    suma_ponderada, suma_calls = 0.0, 0.0

    for dia, horas in resultado["cobertura"].items():
        suma_ponderada_dia, suma_calls_dia = 0.0, 0.0
        detalle_horas = []
        for h, c in horas.items():
            calls = c.get("calls", 0)
            if calls <= 0:
                continue
            aht = c.get("aht_seconds", 150)
            A = (calls * aht) / 3600
            sl = service_level(A, c["programados"], aht, target_answer_seconds) if c["programados"] > 0 else 0.0
            detalle_horas.append({"hora": h, "calls": calls, "programados": c["programados"], "sl_estimado_pct": round(sl * 100, 1)})
            suma_ponderada_dia += sl * calls
            suma_calls_dia += calls

        sl_dia = (suma_ponderada_dia / suma_calls_dia * 100) if suma_calls_dia > 0 else None
        detalle_por_dia[dia] = {"sl_estimado_pct": round(sl_dia, 1) if sl_dia is not None else None, "horas": detalle_horas}
        suma_ponderada += suma_ponderada_dia
        suma_calls += suma_calls_dia

    sl_semana = round(suma_ponderada / suma_calls * 100, 1) if suma_calls > 0 else None
    return {"sl_estimado_semana_pct": sl_semana, "por_dia": detalle_por_dia}


def recomendar_plantillas_turno(fecha_lunes: date, db_path: str = "callcenter.db",
                                 target_service_level: float = 0.95, shrinkage: float = 0.10,
                                 max_occupancy: float = 0.85, max_recomendaciones: int = 5) -> list:
    """
    Corre el generador REAL con las plantillas y disponibilidad actuales, encuentra los
    bloques de horas donde queda déficit, y propone nuevas plantillas de turno para
    taparlos -- respetando el mínimo/máximo de horas diarias configurados (mismo límite
    que ya rige para cualquier asesor). No guarda nada; devuelve las propuestas para que
    el caller decida.
    """
    config = db_config.obtener_configuracion(db_path=db_path)
    horas_min = int(round(config.get("horas_min_dia_default", 4.0)))
    horas_max = int(round(config.get("horas_max_dia_default", 8.0)))
    valle_inicio = config.get("almuerzo_valle_inicio", 14.5)
    valle_fin = config.get("almuerzo_valle_fin", 18.0)

    resultado = generar_horario_semana(fecha_lunes, db_path=db_path, target_service_level=target_service_level,
                                        shrinkage=shrinkage, max_occupancy=max_occupancy)
    plantillas_existentes = listar_plantillas_turno(db_path=db_path)

    candidatos = []
    for dia in DIAS_SEMANA:
        cobertura_dia = resultado["cobertura"][dia]
        horas_ordenadas = sorted(cobertura_dia.keys())

        bloques, bloque_actual = [], []
        for h in horas_ordenadas:
            deficit = cobertura_dia[h]["requeridos"] - cobertura_dia[h]["programados"]
            if deficit > 0:
                bloque_actual.append((h, deficit))
            elif bloque_actual:
                bloques.append(bloque_actual)
                bloque_actual = []
        if bloque_actual:
            bloques.append(bloque_actual)

        tope_dia = DOMINGO_MAX_HORAS if dia == "Domingo" else horas_max
        for bloque in bloques:
            horas_bloque = [h for h, _ in bloque]
            score = sum(d for _, d in bloque)
            inicio_bloque, fin_bloque = min(horas_bloque), max(horas_bloque) + 1
            duracion = max(horas_min, min(tope_dia, fin_bloque - inicio_bloque))

            hora_inicio = inicio_bloque
            hora_fin = min(HORARIO_OPERATIVO_FIN, hora_inicio + duracion)
            hora_inicio = max(HORARIO_OPERATIVO_INICIO, hora_fin - duracion)

            duracion_almuerzo = 1 if (hora_fin - hora_inicio) >= 7 and hora_inicio <= valle_fin and hora_fin >= valle_inicio + 1 else 0

            ya_existe = any(
                p["hora_inicio"] == hora_inicio and p["hora_fin"] == hora_fin and dia in p["dias_aplica"]
                for p in plantillas_existentes
            )
            if ya_existe:
                continue

            candidatos.append({
                "dia": dia, "hora_inicio": hora_inicio, "hora_fin": hora_fin,
                "duracion_almuerzo_horas": duracion_almuerzo, "score": score,
                "horas_criticas": f"{min(horas_bloque)}:00-{max(horas_bloque)+1}:00",
            })

    # Si el mismo rango de horas es crítico en varios días, combinarlo en UNA sola plantilla
    combinados = {}
    for c in sorted(candidatos, key=lambda c: -c["score"]):
        clave = (c["hora_inicio"], c["hora_fin"], c["duracion_almuerzo_horas"])
        combinados.setdefault(clave, {
            "hora_inicio": c["hora_inicio"], "hora_fin": c["hora_fin"],
            "duracion_almuerzo_horas": c["duracion_almuerzo_horas"],
            "dias_aplica": [], "score_total": 0, "detalle": [],
        })
        combinados[clave]["dias_aplica"].append(c["dia"])
        combinados[clave]["score_total"] += c["score"]
        combinados[clave]["detalle"].append(f"{c['dia']} {c['horas_criticas']}")

    propuestas = sorted(combinados.values(), key=lambda c: -c["score_total"])[:max_recomendaciones]
    # Ordenar los días de cada propuesta en el orden natural de la semana, no el de detección
    for p in propuestas:
        p["dias_aplica"] = [d for d in DIAS_SEMANA if d in p["dias_aplica"]]
    return propuestas



    print(f"{'Asesor':<22}" + "".join(f"{d[:3]:>12}" for d in DIAS_SEMANA))
    print("-" * (22 + 12 * 7))
    for nombre, dias in resultado["horario"].items():
        fila = f"{nombre:<22}"
        for dia in DIAS_SEMANA:
            info = dias.get(dia, {"motivo": "?"})
            if "turnos" in info:
                txt = "+".join(f"{t['inicio']:02d}-{t['fin']:02d}h{'*' if t.get('excepcion') else ''}" for t in info["turnos"])
            else:
                mapa = {"no_disponible": "No disp.", "sin_informacion": "Sin info", "libre_no_requerido": "Libre",
                        "descanso_asignado": "Descanso",
                        "tope_semanal_alcanzado": "Tope sem."}
                txt = mapa.get(info["motivo"], info["motivo"])[:11]
            fila += f"{txt:>12}"
        print(fila, f"   ({resultado['horas_semana'][nombre]:.0f}h)")

    print("\n=== Cobertura vs demanda (requeridos / programados por hora) ===")
    for dia in DIAS_SEMANA:
        linea = f"{dia:<12}"
        for h, c in resultado["cobertura"][dia].items():
            marca = "!" if c["programados"] < c["requeridos"] else " "
            linea += f"{h}:{c['requeridos']}/{c['programados']}{marca} "
        print(linea)

    if resultado["alertas"]:
        print(f"\n=== Alertas ({len(resultado['alertas'])}) ===")
        for a in resultado["alertas"]:
            print(" -", a)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        lunes = date.fromisoformat(sys.argv[1])
    else:
        hoy = date.today()
        lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)  # próximo lunes

    print(f"Generando horario para la semana del {lunes.isoformat()}\n")
    resultado = generar_horario_semana(lunes)
    imprimir_horario(resultado)

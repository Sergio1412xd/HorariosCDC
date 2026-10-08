"""
agregados_llamadas.py
Convierte el histórico de llamadas (tabla 'llamadas', que crece semana a semana)
en los promedios por hora que necesita el motor Erlang C:
  - promedio de llamadas contestadas por hora del día
  - promedio de llamadas abandonadas por hora del día
  - TMO (duración promedio de llamadas contestadas) por hora del día

Se puede calcular combinando TODAS las campañas, o separado por campaña
('Pedidos' vs 'Servicio') si decides dimensionar cada una por separado.

A medida que subas más semanas, el promedio se vuelve más robusto (más días de muestra).
"""

import os
import pandas as pd

from db import obtener_llamadas_df


DIA_EN_A_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles", "Thursday": "Jueves",
    "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}


_cache_df_base = {}  # {db_path: (mtime, dataframe_ya_parseado)}


def _cargar_dataframe_base(db_path: str) -> pd.DataFrame:
    """Carga y parsea TODAS las llamadas una sola vez, cacheado en memoria -- se invalida
    solo cuando el archivo de la BD cambia (import de llamadas, etc.), detectado por su
    mtime. Sin esto, una sola generación de horario terminaba leyendo y re-parseando la
    tabla completa de llamadas 3 veces (una por cada función que la necesita), siendo el
    cuello de botella real de rendimiento -- ~38% del tiempo total de generar un horario."""
    try:
        mtime = os.path.getmtime(db_path)
    except OSError:
        mtime = None
    cacheado = _cache_df_base.get(db_path)
    if cacheado is not None and cacheado[0] == mtime:
        return cacheado[1]

    filas = obtener_llamadas_df(db_path=db_path)
    df = pd.DataFrame(filas)
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"])
        df["hora_dt"] = pd.to_datetime(df["hora"], format="%H:%M:%S")
        df["hora_del_dia"] = df["hora_dt"].dt.hour
        df["dia_semana"] = df["fecha"].dt.day_name().map(DIA_EN_A_ES)
    _cache_df_base[db_path] = (mtime, df)
    return df


def _cargar_dataframe(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None,
                       hora_inicio: int = None, hora_fin: int = None) -> pd.DataFrame:
    df = _cargar_dataframe_base(db_path)
    if df.empty:
        return df

    if fecha_inicio:
        df = df[df["fecha"] >= pd.to_datetime(fecha_inicio)]
    if fecha_fin:
        df = df[df["fecha"] <= pd.to_datetime(fecha_fin)]
    if hora_inicio is not None:
        df = df[df["hora_del_dia"] >= hora_inicio]
    if hora_fin is not None:
        df = df[df["hora_del_dia"] <= hora_fin]

    return df


def resumen_por_hora(db_path: str = "callcenter.db", campana: str = None,
                      fecha_inicio: str = None, fecha_fin: str = None) -> pd.DataFrame:
    """
    Devuelve un DataFrame con una fila por hora del día (0-23) y columnas:
      llamadas_contestadas_prom_dia, llamadas_abandonadas_prom_dia, tmo_seg_prom, dias_observados
    'llamadas_..._prom_dia' ya está promediado por la cantidad de DÍAS distintos en el histórico,
    listo para pasarle directo a required_agents().
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if df.empty:
        return pd.DataFrame()

    if campana:
        df = df[df["campana"] == campana]

    dias_totales = df["fecha"].dt.date.nunique()

    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]

    conteo_contestadas = contestadas.groupby("hora_del_dia").size()
    conteo_abandonadas = abandonadas.groupby("hora_del_dia").size()
    tmo_por_hora = contestadas.groupby("hora_del_dia")["duracion_seg"].mean()

    todas_horas = range(0, 24)
    tabla = pd.DataFrame({
        "hora_del_dia": todas_horas,
        "llamadas_contestadas_prom_dia": [round(conteo_contestadas.get(h, 0) / dias_totales, 1) for h in todas_horas],
        "llamadas_abandonadas_prom_dia": [round(conteo_abandonadas.get(h, 0) / dias_totales, 1) for h in todas_horas],
        "tmo_seg_prom": [round(tmo_por_hora.get(h, 0), 0) for h in todas_horas],
    })
    tabla["dias_observados"] = dias_totales
    # Quitamos horas sin ninguna actividad (operación cerrada esa hora)
    tabla = tabla[(tabla["llamadas_contestadas_prom_dia"] > 0) | (tabla["llamadas_abandonadas_prom_dia"] > 0)]
    return tabla.reset_index(drop=True)


def resumen_por_dia_semana_y_hora(db_path: str = "callcenter.db", campana: str = None,
                                   fecha_inicio: str = None, fecha_fin: str = None) -> pd.DataFrame:
    """
    Igual que resumen_por_hora pero separado por día de la semana (Lunes, Martes...).
    Útil porque el tráfico de un sábado normalmente es muy distinto al de un martes,
    y promediarlos juntos puede sub/sobre-dimensionar algunos días.
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if df.empty:
        return pd.DataFrame()

    if campana:
        df = df[df["campana"] == campana]

    dias_por_nombre = df.groupby("dia_semana")["fecha"].apply(lambda s: s.dt.date.nunique())

    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]

    filas = []
    for dia_nombre, n_dias in dias_por_nombre.items():
        c_dia = contestadas[contestadas["dia_semana"] == dia_nombre]
        a_dia = abandonadas[abandonadas["dia_semana"] == dia_nombre]
        conteo_c = c_dia.groupby("hora_del_dia").size()
        conteo_a = a_dia.groupby("hora_del_dia").size()
        tmo_h = c_dia.groupby("hora_del_dia")["duracion_seg"].mean()

        for h in sorted(set(conteo_c.index) | set(conteo_a.index)):
            filas.append({
                "dia_semana": dia_nombre,
                "hora_del_dia": h,
                "llamadas_contestadas_prom_dia": round(conteo_c.get(h, 0) / n_dias, 1),
                "llamadas_abandonadas_prom_dia": round(conteo_a.get(h, 0) / n_dias, 1),
                "tmo_seg_prom": round(tmo_h.get(h, 0), 0),
                "dias_observados": n_dias,
            })

    return pd.DataFrame(filas)


def metricas_generales(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None,
                        hora_inicio: int = None, hora_fin: int = None) -> dict:
    """
    KPIs generales para el dashboard: totales, % contestadas, TMO promedio,
    y series (por día y por hora) listas para graficar. Acepta filtros opcionales
    de rango de fechas y rango de horas del día.
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                            hora_inicio=hora_inicio, hora_fin=hora_fin)
    if df.empty:
        return None

    total = len(df)
    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]
    tmo_promedio = contestadas["duracion_seg"].mean() if len(contestadas) else 0
    espera_promedio_abandono = abandonadas["espera_seg"].mean() if len(abandonadas) else 0

    serie_diaria = (
        df.groupby([df["fecha"].dt.strftime("%Y-%m-%d"), "resultado"]).size()
        .unstack(fill_value=0).reset_index().rename(columns={"fecha": "fecha"})
    )
    serie_diaria_lista = []
    for _, fila in serie_diaria.iterrows():
        c = int(fila.get("Contestada", 0))
        a = int(fila.get("Abandonada", 0))
        serie_diaria_lista.append({
            "fecha": fila["fecha"], "contestadas": c, "abandonadas": a,
            "pct_contestadas": round(c / (c + a) * 100, 1) if (c + a) > 0 else 100.0,
        })

    return {
        "total_llamadas": total,
        "contestadas": len(contestadas),
        "abandonadas": len(abandonadas),
        "pct_contestadas": round(len(contestadas) / total * 100, 1) if total else 0,
        "tmo_promedio_seg": round(tmo_promedio, 0),
        "espera_promedio_abandono_seg": round(espera_promedio_abandono, 0),
        "dias_con_datos": df["fecha"].dt.date.nunique(),
        "serie_diaria": serie_diaria_lista,
        "por_hora": resumen_por_hora(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin).to_dict(orient="records"),
    }


def listar_semanas_disponibles(db_path: str = "callcenter.db") -> list:
    """Devuelve cada semana (lunes a domingo) presente en el histórico de llamadas, con su
    total de llamadas contestadas -- para que el usuario pueda elegir en cuáles basar el
    pronóstico de demanda, en vez de usar siempre todo el histórico. Incluye el número de
    semana ISO (ej. 'Sem 35') y si esa semana tuvo algún festivo, para marcarla distinto
    en el selector -- una semana con festivo no es representativa de una semana normal."""
    from festivos import listar_festivos_rango

    df = _cargar_dataframe(db_path)
    if df.empty:
        return []

    contestadas = df[df["resultado"] == "Contestada"].copy()
    contestadas["fecha_lunes"] = contestadas["fecha"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())

    resumen = contestadas.groupby("fecha_lunes").size().reset_index(name="llamadas_contestadas")
    resumen = resumen.sort_values("fecha_lunes", ascending=False)

    resultado = []
    for _, fila in resumen.iterrows():
        lunes = fila["fecha_lunes"]
        domingo = lunes + pd.Timedelta(days=6)
        festivos_semana = listar_festivos_rango(lunes, domingo.date() if hasattr(domingo, "date") else domingo)
        resultado.append({
            "fecha_lunes": lunes.isoformat(), "fecha_domingo": domingo.isoformat(),
            "llamadas_contestadas": int(fila["llamadas_contestadas"]),
            "numero_semana": lunes.isocalendar()[1],
            "tiene_festivo": len(festivos_semana) > 0,
            "festivos": [f["nombre"] for f in festivos_semana],
        })
    return resultado


def resumen_por_dia_semana_y_hora_semanas(db_path: str, semanas_lunes: list, campana: str = None) -> pd.DataFrame:
    """Igual que resumen_por_dia_semana_y_hora_ponderado, pero en vez de usar todo el
    histórico con decaimiento, promedia SOLO las semanas específicas que el usuario eligió
    (todas con el mismo peso) -- útil para excluir semanas atípicas (paros, errores de
    datos, promociones puntuales) o para basarse en una sola semana representativa.
    'semanas_lunes': lista de fechas (date o 'YYYY-MM-DD') del LUNES de cada semana a incluir.
    """
    df = _cargar_dataframe(db_path)
    if df.empty:
        return pd.DataFrame()
    if campana:
        df = df[df["campana"] == campana]

    lunes_deseados = {pd.Timestamp(l).date() if not isinstance(l, str) else pd.Timestamp(l).date()
                       for l in semanas_lunes}
    df["fecha_lunes_semana"] = df["fecha"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    df = df[df["fecha_lunes_semana"].isin(lunes_deseados)]
    if df.empty:
        return pd.DataFrame()

    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]

    filas = []
    for dia_nombre, grupo_dia in contestadas.groupby("dia_semana"):
        n_fechas = grupo_dia["fecha"].nunique()
        grupo_ab_dia = abandonadas[abandonadas["dia_semana"] == dia_nombre]
        for h in range(24):
            c_hora = grupo_dia[grupo_dia["hora_del_dia"] == h]
            a_hora = grupo_ab_dia[grupo_ab_dia["hora_del_dia"] == h]
            if len(c_hora) == 0 and len(a_hora) == 0:
                continue
            filas.append({
                "dia_semana": dia_nombre, "hora_del_dia": h,
                "llamadas_contestadas_prom_dia": round(len(c_hora) / n_fechas, 1) if n_fechas else 0,
                "llamadas_abandonadas_prom_dia": round(len(a_hora) / n_fechas, 1) if n_fechas else 0,
                "tmo_seg_prom": round(c_hora["duracion_seg"].mean(), 0) if len(c_hora) else 0,
                "dias_observados": n_fechas,
            })
    return pd.DataFrame(filas)


def resumen_por_dia_semana_y_hora_ponderado(db_path: str = "callcenter.db", campana: str = None,
                                             factor_decaimiento: float = 0.7) -> pd.DataFrame:
    """
    Igual que resumen_por_dia_semana_y_hora, pero pondera más las semanas RECIENTES que las
    antiguas -- así, si el tráfico de los domingos ha ido subiendo semana a semana, el promedio
    refleja más la tendencia actual que el mes completo mezclado en partes iguales.

    factor_decaimiento: qué tanto pesa una semana comparada con la inmediatamente más reciente.
    Ej. 0.7 -> la semana pasada pesa 100%, la anterior 70%, la anterior a esa 49%, etc.
    Usa 1.0 para volver a un promedio plano (todas las semanas pesan igual).
    """
    df = _cargar_dataframe(db_path)
    if df.empty:
        return pd.DataFrame()
    if campana:
        df = df[df["campana"] == campana]

    fecha_max = df["fecha"].max()
    fechas_unicas = df[["fecha", "dia_semana"]].drop_duplicates().reset_index(drop=True)
    fechas_unicas["semanas_atras"] = (fecha_max - fechas_unicas["fecha"]).dt.days // 7
    fechas_unicas["peso"] = factor_decaimiento ** fechas_unicas["semanas_atras"]
    peso_por_fecha = dict(zip(fechas_unicas["fecha"], fechas_unicas["peso"]))

    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]

    conteo_c = contestadas.groupby(["fecha", "hora_del_dia"]).size()
    conteo_a = abandonadas.groupby(["fecha", "hora_del_dia"]).size()
    tmo_fh = contestadas.groupby(["fecha", "hora_del_dia"])["duracion_seg"].mean()

    filas = []
    for dia_nombre, grupo in fechas_unicas.groupby("dia_semana"):
        fechas_dia = grupo["fecha"].tolist()
        suma_pesos = sum(peso_por_fecha[f] for f in fechas_dia)

        for h in range(24):
            suma_pond_c = sum(peso_por_fecha[f] * conteo_c.get((f, h), 0) for f in fechas_dia)
            suma_pond_a = sum(peso_por_fecha[f] * conteo_a.get((f, h), 0) for f in fechas_dia)
            c_prom = suma_pond_c / suma_pesos
            a_prom = suma_pond_a / suma_pesos

            if c_prom > 0 or a_prom > 0:
                tmos = [tmo_fh[(f, h)] for f in fechas_dia if (f, h) in tmo_fh.index and not pd.isna(tmo_fh[(f, h)])]
                filas.append({
                    "dia_semana": dia_nombre, "hora_del_dia": h,
                    "llamadas_contestadas_prom_dia": round(c_prom, 1),
                    "llamadas_abandonadas_prom_dia": round(a_prom, 1),
                    "tmo_seg_prom": round(sum(tmos) / len(tmos), 0) if tmos else 0,
                    "dias_observados": len(fechas_dia),
                })

    return pd.DataFrame(filas)


def tendencia_semanal_por_dia(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None) -> pd.DataFrame:
    """
    Devuelve, por cada fecha, el total de llamadas contestadas Y abandonadas ese día, junto
    con su día de la semana -- para graficar cómo ha ido cambiando cada día (ej. ¿los
    domingos están subiendo semana a semana?, ¿está subiendo el % de llamadas caídas?).
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if df.empty:
        return pd.DataFrame()
    contestadas = df[df["resultado"] == "Contestada"].groupby(
        [df["fecha"].dt.strftime("%Y-%m-%d"), "dia_semana"]).size().reset_index(name="contestadas")
    contestadas.columns = ["fecha", "dia_semana", "contestadas"]
    abandonadas = df[df["resultado"] == "Abandonada"].groupby(
        [df["fecha"].dt.strftime("%Y-%m-%d"), "dia_semana"]).size().reset_index(name="abandonadas")
    abandonadas.columns = ["fecha", "dia_semana", "abandonadas"]
    diario = pd.merge(contestadas, abandonadas, on=["fecha", "dia_semana"], how="outer").fillna(0)
    diario["contestadas"] = diario["contestadas"].astype(int)
    diario["abandonadas"] = diario["abandonadas"].astype(int)
    return diario.sort_values("fecha")


def tendencia_semanal_matriz(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None) -> dict:
    """
    Arma una matriz {dia_semana: [valor_semana1, valor_semana2, ...]} de llamadas
    contestadas, agrupando las fechas por semana ISO -- para graficar cómo evoluciona
    cada día de la semana (¿los domingos vienen subiendo?). También arma la matriz
    equivalente de % de llamadas caídas por día, para la línea de tendencia superpuesta.
    """
    diario = tendencia_semanal_por_dia(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if diario.empty:
        return {}

    diario["fecha_dt"] = pd.to_datetime(diario["fecha"])
    diario["semana_iso"] = diario["fecha_dt"].dt.isocalendar().week
    semanas_ordenadas = sorted(diario["semana_iso"].unique())

    orden = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    matriz = {dia: [] for dia in orden}
    matriz_pct_caidas = {dia: [] for dia in orden}
    for dia in orden:
        for semana in semanas_ordenadas:
            fila = diario[(diario["dia_semana"] == dia) & (diario["semana_iso"] == semana)]
            if len(fila):
                c, a = int(fila["contestadas"].iloc[0]), int(fila["abandonadas"].iloc[0])
                matriz[dia].append(c)
                matriz_pct_caidas[dia].append(round((a / (c + a)) * 100, 1) if (c + a) > 0 else None)
            else:
                matriz[dia].append(None)
                matriz_pct_caidas[dia].append(None)

    return {"semanas": [f"Sem {s}" for s in semanas_ordenadas], "por_dia": matriz, "por_dia_pct_caidas": matriz_pct_caidas}


def resumen_simple_por_dia_semana(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None) -> list:
    """
    Tabla de transparencia: para cada día de la semana, promedio/mínimo/máximo de llamadas
    contestadas y abandonadas, cuántas veces se observó ese día en el histórico, y el TMO
    promedio. Pensada para que se pueda verificar a simple vista que los promedios que usa
    el sistema tienen sentido frente a los datos crudos.
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if df.empty:
        return []

    contestadas = df[df["resultado"] == "Contestada"]
    abandonadas = df[df["resultado"] == "Abandonada"]

    por_fecha_c = contestadas.groupby([df["fecha"].dt.date, "dia_semana"]).size().reset_index(name="contestadas")
    por_fecha_c.columns = ["fecha", "dia_semana", "contestadas"]
    por_fecha_a = abandonadas.groupby([df["fecha"].dt.date, "dia_semana"]).size().reset_index(name="abandonadas")
    por_fecha_a.columns = ["fecha", "dia_semana", "abandonadas"]

    fusion = pd.merge(por_fecha_c, por_fecha_a[["fecha", "abandonadas"]], on="fecha", how="outer").fillna(0)
    tmo_por_fecha = contestadas.groupby(df["fecha"].dt.date)["duracion_seg"].mean()

    orden = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    resultado = []
    for dia in orden:
        sub = fusion[fusion["dia_semana"] == dia]
        if sub.empty:
            continue
        tmos = [tmo_por_fecha.get(f) for f in sub["fecha"] if not pd.isna(tmo_por_fecha.get(f, float("nan")))]
        contestadas_prom = round(sub["contestadas"].mean(), 0)
        abandonadas_prom = round(sub["abandonadas"].mean(), 0)
        total_prom = contestadas_prom + abandonadas_prom
        resultado.append({
            "dia_semana": dia,
            "dias_observados": len(sub),
            "contestadas_promedio": contestadas_prom,
            "contestadas_min": int(sub["contestadas"].min()),
            "contestadas_max": int(sub["contestadas"].max()),
            "abandonadas_promedio": abandonadas_prom,
            "pct_caidas_promedio": round((abandonadas_prom / total_prom) * 100, 1) if total_prom > 0 else 0,
            "tmo_seg_promedio": round(sum(tmos) / len(tmos), 0) if tmos else 0,
        })
    return resultado


def rendimiento_por_agente(db_path: str = "callcenter.db", fecha_inicio: str = None, fecha_fin: str = None) -> list:
    """
    Productividad de cada asesor en el rango de fechas filtrado: llamadas contestadas,
    TMO promedio, tiempo total en llamada, días con actividad y promedio de llamadas
    por día activo. Solo cuenta llamadas CONTESTADAS (las abandonadas no tienen agente).
    """
    df = _cargar_dataframe(db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    if df.empty:
        return []

    contestadas = df[(df["resultado"] == "Contestada") & df["agente"].notna()]
    if contestadas.empty:
        return []

    resultado = []
    for agente, grupo in contestadas.groupby("agente"):
        dias_activos = grupo["fecha"].dt.date.nunique()
        tiempo_total = grupo["duracion_seg"].sum()
        resultado.append({
            "agente": agente,
            "llamadas_contestadas": len(grupo),
            "tmo_promedio_seg": round(grupo["duracion_seg"].mean(), 0),
            "tiempo_total_atencion_seg": int(tiempo_total),
            "dias_activos": int(dias_activos),
            "promedio_llamadas_por_dia": round(len(grupo) / dias_activos, 1) if dias_activos else 0,
        })

    resultado.sort(key=lambda r: -r["llamadas_contestadas"])
    return resultado


if __name__ == "__main__":
    print("=== Resumen combinado (todas las campañas), promedio por hora del día ===\n")
    tabla = resumen_por_hora()
    print(tabla.to_string(index=False))

    print("\n\n=== Igual, separado por campaña ===")
    for camp in ["Pedidos", "Servicio"]:
        print(f"\n--- {camp} ---")
        print(resumen_por_hora(campana=camp).to_string(index=False))

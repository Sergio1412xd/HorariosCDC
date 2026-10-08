"""
festivos.py
Detecta festivos colombianos (con la librería 'holidays', que ya incluye la Ley Emiliani)
y compara automáticamente el tráfico de un festivo próximo contra festivos anteriores
similares, para que el generador de horarios use el patrón de demanda correcto en vez
del patrón normal de ese día de la semana.
"""

from datetime import date

import holidays
import pandas as pd

from agregados_llamadas import _cargar_dataframe

_CO_FESTIVOS = holidays.Colombia(years=range(2020, 2031))


def es_festivo(fecha: date) -> bool:
    return fecha in _CO_FESTIVOS


def nombre_festivo(fecha: date) -> str:
    return _CO_FESTIVOS.get(fecha, "")


def listar_festivos_rango(fecha_inicio: date, fecha_fin: date) -> list:
    """Festivos entre dos fechas (inclusive), con nombre."""
    return sorted(
        [{"fecha": f.isoformat(), "nombre": n} for f, n in _CO_FESTIVOS.items() if fecha_inicio <= f <= fecha_fin],
        key=lambda x: x["fecha"],
    )


def resumen_festivos_historicos(db_path: str = "callcenter.db") -> dict:
    """
    Busca, dentro del histórico de llamadas cargado, qué fechas fueron festivo, y arma
    el patrón promedio de llamadas por hora en esos días (para usarlo como demanda de
    un festivo futuro en vez del patrón normal del día de la semana).
    También compara cada festivo encontrado contra el promedio de ESE mismo día de la
    semana en semanas NO festivas, para ver si el festivo sube o baja el tráfico.
    """
    df = _cargar_dataframe(db_path)
    if df.empty:
        return {"festivos_encontrados": [], "patron_por_hora": {}}

    fechas_unicas = df["fecha"].dt.date.unique()
    fechas_festivo = [f for f in fechas_unicas if es_festivo(f)]

    if not fechas_festivo:
        return {"festivos_encontrados": [], "patron_por_hora": {}}

    contestadas = df[df["resultado"] == "Contestada"]

    # ---- Patrón promedio por hora en días festivos ----
    df_festivos = contestadas[contestadas["fecha"].dt.date.isin(fechas_festivo)]
    conteo_por_hora = df_festivos.groupby("hora_del_dia").size()
    tmo_por_hora = df_festivos.groupby("hora_del_dia")["duracion_seg"].mean()
    n_festivos = len(fechas_festivo)

    patron_por_hora = {
        int(h): {
            "llamadas_contestadas_prom_dia": round(conteo_por_hora.get(h, 0) / n_festivos, 1),
            "tmo_seg_prom": round(tmo_por_hora.get(h, 0), 0) if not pd.isna(tmo_por_hora.get(h, float("nan"))) else 150,
        }
        for h in range(24) if conteo_por_hora.get(h, 0) > 0
    }

    # ---- Comparación festivo vs mismo día de semana no festivo ----
    festivos_detalle = []
    for f in sorted(fechas_festivo):
        dia_semana_en = pd.Timestamp(f).day_name()
        total_festivo = len(contestadas[contestadas["fecha"].dt.date == f])

        mismo_dia_no_festivo = contestadas[
            (contestadas["fecha"].dt.day_name() == dia_semana_en) &
            (~contestadas["fecha"].dt.date.isin(fechas_festivo))
        ]
        totales_por_fecha = mismo_dia_no_festivo.groupby(mismo_dia_no_festivo["fecha"].dt.date).size()
        promedio_no_festivo = round(totales_por_fecha.mean(), 1) if len(totales_por_fecha) else None

        variacion = None
        if promedio_no_festivo:
            variacion = round((total_festivo - promedio_no_festivo) / promedio_no_festivo * 100, 1)

        festivos_detalle.append({
            "fecha": f.isoformat(), "nombre": nombre_festivo(f), "dia_semana": dia_semana_en,
            "llamadas_contestadas": int(total_festivo),
            "promedio_mismo_dia_no_festivo": promedio_no_festivo,
            "variacion_pct": variacion,
        })

    return {"festivos_encontrados": festivos_detalle, "patron_por_hora": patron_por_hora,
            "n_festivos_en_historico": n_festivos}


if __name__ == "__main__":
    import json
    r = resumen_festivos_historicos()
    print(json.dumps(r, indent=2, ensure_ascii=False))

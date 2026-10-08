"""
calcular_dimensionamiento.py
Pipeline completo: histórico real de llamadas (tabla 'llamadas') -> agregados por hora -> Erlang C.

Esto reemplaza el demo manual que usamos al principio (demo_con_tus_datos.py) por datos
reales y que se actualizan solos cada vez que cargas una semana nueva con loader_llamadas.py.
"""

from agregados_llamadas import resumen_por_hora
from erlang import required_agents


def calcular(db_path: str = "callcenter.db", campana: str = None,
             target_service_level: float = 0.95, shrinkage: float = 0.30):
    tabla = resumen_por_hora(db_path=db_path, campana=campana)
    if tabla.empty:
        print("No hay llamadas cargadas todavía.")
        return

    print(f"{'Hora':>5}{'Llam/día':>10}{'TMO(s)':>8}{'Ag.necesarios':>15}{'SL%':>7}{'Ocup%':>8}")
    print("-" * 55)

    for _, fila in tabla.iterrows():
        r = required_agents(
            calls=round(fila["llamadas_contestadas_prom_dia"]),
            aht_seconds=fila["tmo_seg_prom"] if fila["tmo_seg_prom"] > 0 else 150,
            target_service_level=target_service_level,
            shrinkage=shrinkage,
        )
        print(f"{int(fila['hora_del_dia']):>5}{fila['llamadas_contestadas_prom_dia']:>10}"
              f"{fila['tmo_seg_prom']:>8}{r.agents_final:>15}{r.service_level_pct:>7}{r.occupancy_pct:>8}")

    print(f"\n(Basado en {int(tabla['dias_observados'].iloc[0])} días de histórico real"
          + (f", campaña: {campana}" if campana else ", todas las campañas combinadas") + ")")


if __name__ == "__main__":
    print("=== DIMENSIONAMIENTO — todas las campañas combinadas ===\n")
    calcular()

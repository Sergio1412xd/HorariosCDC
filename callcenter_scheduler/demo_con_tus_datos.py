"""
Prueba del motor Erlang C usando los datos de tu tabla (imagen que subiste).

IMPORTANTE: esta tabla es el ACUMULADO DE JULIO COMPLETO (01 al 31 de julio = 31 días).
Cada celda de 'Llamadas Contestadas' es la suma del mes en esa franja horaria, NO de un solo día.
Para dimensionar personal por hora necesitamos el PROMEDIO DIARIO, así que dividimos
las llamadas por el número de días del periodo.

El TMO (Duración Promedio de Llamada Contestada) NO se divide: ya es un promedio, no un total.
"""

from erlang import required_agents

DIAS_DEL_PERIODO = 31  # 01 jul - 31 jul

# (hora, llamadas_contestadas_TOTAL_MES, tmo_mm_ss promedio)
datos = [
    ("11 a 12", 1433, "2:41"),
    ("12 a 13", 2908, "2:37"),
    ("13 a 14", 3288, "2:38"),
    ("14 a 15", 3192, "2:31"),
    ("15 a 16", 2852, "2:26"),
    ("16 a 17", 2136, "2:31"),
    ("17 a 18", 1743, "2:32"),
    ("18 a 19", 2164, "2:39"),
    ("19 a 20", 3217, "2:32"),
    ("20 a 21", 3628, "2:17"),
    ("21 a 22", 1094, "2:28"),
    ("22 a 23", 15,   "4:21"),
]


def mmss_a_segundos(t: str) -> float:
    m, s = t.split(":")
    return int(m) * 60 + int(s)


print(f"{'Hora':<10}{'Llam/día':>10}{'TMO':>7}{'Ag.85%':>9}{'Ag.95%':>9}{'Dif.':>6}{'SL@95%':>9}{'Ocup@95%':>10}")
print("-" * 70)

total_85 = 0
total_95 = 0
for hora, llamadas_mes, tmo in datos:
    llamadas_dia = round(llamadas_mes / DIAS_DEL_PERIODO)
    tmo_seg = mmss_a_segundos(tmo)

    r85 = required_agents(calls=llamadas_dia, aht_seconds=tmo_seg, target_service_level=0.85, shrinkage=0.30)
    r95 = required_agents(calls=llamadas_dia, aht_seconds=tmo_seg, target_service_level=0.95, shrinkage=0.30)

    total_85 += r85.agents_final
    total_95 += r95.agents_final
    dif = r95.agents_final - r85.agents_final

    print(f"{hora:<10}{llamadas_dia:>10}{tmo:>7}{r85.agents_final:>9}{r95.agents_final:>9}{dif:>6}{r95.service_level_pct:>9}{r95.occupancy_pct:>10}")

print("-" * 70)
print(f"{'TOTAL persona-hora/día:':<27}{total_85:>19}{total_95:>9}{total_95-total_85:>6}")
print(f"\nIr de 85% -> 95% de nivel de servicio cuesta {total_95-total_85} persona-hora MÁS por día "
      f"({round((total_95/total_85-1)*100,1)}% más costo de planilla en el día).")


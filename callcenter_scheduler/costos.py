"""
costos.py
Calcula el costo de un horario generado, aplicando las tarifas configurables:
  - valor_hora_normal: tarifa base por hora trabajada
  - valor_recargo_dominical: tarifa por hora trabajada en domingo (REEMPLAZA la hora normal ese día)
  - valor_recargo_nocturno: adicional por hora trabajada desde las 19:00 (se SUMA a la tarifa base)
  - valor_subsidio_transporte_hora: adicional por cada hora trabajada, cualquier día/horario

Las tarifas se leen de la base de datos (tabla 'tarifas'), así que cualquier cambio hecho
desde la interfaz web se refleja de inmediato en el cálculo, sin tocar código.
"""

from db import obtener_tarifas, DIAS_SEMANA, obtener_configuracion_valor
from generador_horarios import horas_pagables_turno

HORA_INICIO_RECARGO_NOCTURNO = 19  # 7:00 p.m., según lo definido por el negocio


def costo_hora(dia_semana: str, hora: int, tarifas: dict, hora_inicio_recargo_nocturno: int = None) -> dict:
    """Costo de UNA hora trabajada, desglosado. 'hora' es la hora de inicio de ese bloque (ej. 19 = 19:00-20:00)."""
    if hora_inicio_recargo_nocturno is None:
        hora_inicio_recargo_nocturno = HORA_INICIO_RECARGO_NOCTURNO
    es_domingo = dia_semana == "Domingo"
    es_nocturna = hora >= hora_inicio_recargo_nocturno

    base = tarifas["valor_recargo_dominical"] if es_domingo else tarifas["valor_hora_normal"]
    recargo_nocturno = tarifas["valor_recargo_nocturno"] if es_nocturna else 0.0
    transporte = tarifas["valor_subsidio_transporte_hora"]

    total = base + recargo_nocturno + transporte
    return {
        "base": base, "recargo_nocturno": recargo_nocturno, "transporte": transporte,
        "total": total, "es_domingo": es_domingo, "es_nocturna": es_nocturna,
    }


def costo_turno(dia_semana: str, hora_inicio: int, hora_fin: int, tarifas: dict,
                 hora_inicio_recargo_nocturno: int = None) -> float:
    return sum(costo_hora(dia_semana, h, tarifas, hora_inicio_recargo_nocturno)["total"]
               for h in range(hora_inicio, hora_fin))


def calcular_costo_horario(resultado_horario: dict, db_path: str = "callcenter.db") -> dict:
    """
    Recibe el resultado de generador_horarios.generar_horario_semana() y devuelve:
      - costo_por_empleado: {nombre: costo_semana}
      - costo_por_dia: {dia: costo_dia}
      - desglose: {base, recargo_nocturno, recargo_dominical_extra, transporte}
      - total_semana
    """
    tarifas = obtener_tarifas(db_path=db_path)
    hora_inicio_recargo_nocturno = obtener_configuracion_valor("hora_inicio_recargo_nocturno", HORA_INICIO_RECARGO_NOCTURNO, db_path=db_path)

    costo_por_empleado = {}
    costo_por_dia = {dia: 0.0 for dia in DIAS_SEMANA}
    total_base = total_nocturno = total_transporte = 0.0
    # Para mostrar cuánto EXTRA cuesta el domingo comparado con si fuera tarifa normal
    total_extra_dominical = 0.0

    for nombre, dias in resultado_horario["horario"].items():
        costo_por_empleado[nombre] = 0.0
        for dia, info in dias.items():
            if "turnos" not in info:
                continue
            for turno in info["turnos"]:
                for h in horas_pagables_turno(turno):
                    c = costo_hora(dia, h, tarifas, hora_inicio_recargo_nocturno)
                    costo_por_empleado[nombre] += c["total"]
                    costo_por_dia[dia] += c["total"]
                    total_nocturno += c["recargo_nocturno"]
                    total_transporte += c["transporte"]
                    if c["es_domingo"]:
                        total_base += tarifas["valor_hora_normal"]  # como referencia comparativa
                        total_extra_dominical += (tarifas["valor_recargo_dominical"] - tarifas["valor_hora_normal"])
                    else:
                        total_base += c["base"]

    total_semana = sum(costo_por_empleado.values())

    return {
        "costo_por_empleado": costo_por_empleado,
        "costo_por_dia": costo_por_dia,
        "desglose": {
            "base_hora_normal_equivalente": round(total_base, 0),
            "extra_por_recargo_dominical": round(total_extra_dominical, 0),
            "recargo_nocturno": round(total_nocturno, 0),
            "subsidio_transporte": round(total_transporte, 0),
        },
        "total_semana": round(total_semana, 0),
        "tarifas_usadas": tarifas,
    }


if __name__ == "__main__":
    import sys
    from datetime import date, timedelta
    from generador_horarios import generar_horario_semana

    if len(sys.argv) > 1:
        lunes = date.fromisoformat(sys.argv[1])
    else:
        hoy = date.today()
        lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)

    resultado = generar_horario_semana(lunes)
    costo = calcular_costo_horario(resultado)

    print(f"=== Costo del horario — semana del {lunes.isoformat()} ===\n")
    for dia, monto in costo["costo_por_dia"].items():
        print(f"  {dia:<12} ${monto:>14,.0f}")
    print(f"\n  {'TOTAL SEMANA':<12} ${costo['total_semana']:>14,.0f}\n")

    print("Desglose:")
    for k, v in costo["desglose"].items():
        print(f"  {k:<32} ${v:>14,.0f}")

    print("\nPor asesor:")
    for nombre, monto in sorted(costo["costo_por_empleado"].items(), key=lambda x: -x[1]):
        print(f"  {nombre:<25} ${monto:>12,.0f}")

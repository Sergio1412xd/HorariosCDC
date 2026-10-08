"""
validar_disponibilidad.py
Calcula, para cada empleado, cuántas horas de disponibilidad tiene en la semana
(sumando sus rangos/"Completa" por día) y valida contra sus horas_min_semana / horas_max_semana.

Esto es clave ANTES de generar horarios: si alguien tiene menos horas disponibles que su
mínimo contractual, es imposible cuadrarlo en el horario sin violar una de las dos reglas.
"""

from datetime import datetime

from db import listar_empleados, obtener_disponibilidad

# Horario operativo del call center (usado para "Completa"). Ajusta si tu operación
# abre/cierra distinto. Basado en tu tabla, opera aprox. 11:00 a 23:00.
HORARIO_OPERATIVO_INICIO = "11:00"
HORARIO_OPERATIVO_FIN = "23:00"


def _horas_entre(hi: str, hf: str) -> float:
    t1 = datetime.strptime(hi, "%H:%M")
    t2 = datetime.strptime(hf, "%H:%M")
    return (t2 - t1).total_seconds() / 3600


def horas_disponibles_por_dia(disponibilidad_dia: dict) -> float:
    tipo = disponibilidad_dia["tipo"]
    if tipo == "completa":
        return _horas_entre(HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN)
    if tipo == "rango":
        return _horas_entre(disponibilidad_dia["hora_inicio"], disponibilidad_dia["hora_fin"])
    return 0.0  # no_disponible / sin_informacion


def validar_todos(db_path: str = "callcenter.db"):
    resultados = []
    for emp in listar_empleados(db_path=db_path):
        disp = obtener_disponibilidad(emp["id"], db_path=db_path)

        horas_por_dia = {}
        dias_sin_info = []
        for dia, d in disp.items():
            if d["tipo"] == "sin_informacion":
                dias_sin_info.append(dia)
            horas_por_dia[dia] = horas_disponibles_por_dia(d)

        total_semana = sum(horas_por_dia.values())

        alertas = []
        if dias_sin_info:
            alertas.append(f"Sin información en: {', '.join(dias_sin_info)}")
        if total_semana < emp["horas_min_semana"]:
            alertas.append(
                f"Disponibilidad total ({total_semana:.1f}h) NO alcanza el mínimo semanal "
                f"({emp['horas_min_semana']}h) — imposible cumplir su contrato con la disponibilidad actual"
            )

        dias_utiles_min = [dia for dia, h in horas_por_dia.items() if 0 < h < emp["horas_min_dia"]]
        if dias_utiles_min:
            alertas.append(
                f"Días con ventana de disponibilidad MENOR al mínimo diario ({emp['horas_min_dia']}h), "
                f"no se le puede programar turno esos días sin violar el mínimo: {', '.join(dias_utiles_min)}"
            )

        resultados.append({
            "empleado": emp["nombre"],
            "horas_disponibles_semana": round(total_semana, 1),
            "horas_min_semana": emp["horas_min_semana"],
            "horas_max_semana": emp["horas_max_semana"],
            "alertas": alertas,
        })
    return resultados


if __name__ == "__main__":
    resultados = validar_todos()

    print(f"{'Empleado':<25}{'Disp.Semana':>13}{'Min':>6}{'Max':>6}   Estado")
    print("-" * 90)
    for r in resultados:
        estado = "⚠ REVISAR" if r["alertas"] else "OK"
        print(f"{r['empleado']:<25}{r['horas_disponibles_semana']:>13}{r['horas_min_semana']:>6}{r['horas_max_semana']:>6}   {estado}")
        for a in r["alertas"]:
            print(f"      -> {a}")

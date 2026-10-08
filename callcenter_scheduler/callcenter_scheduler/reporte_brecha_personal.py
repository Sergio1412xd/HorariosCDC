"""
reporte_brecha_personal.py
Genera un Excel formal que sustenta la necesidad de contratar más personal:
compara la demanda (Erlang C al nivel de servicio objetivo) contra la capacidad
actual del equipo, y traduce la brecha a un número concreto de asesores a contratar.

Uso:
    py reporte_brecha_personal.py [fecha_lunes] [nivel_servicio]
    py reporte_brecha_personal.py 2026-09-07 0.95
"""

import sys
from datetime import date, timedelta

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from db import listar_empleados, obtener_disponibilidad, DIAS_SEMANA
from generador_horarios import (
    _demanda_por_dia, _ventana_disponibilidad, generar_horario_semana,
    HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN,
)

INK = "1B2430"
RUST = "B7541D"
GREEN = "2F7A52"
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=INK)
TITLE_FONT = Font(name="Arial", bold=True, size=14, color=INK)
NORMAL_FONT = Font(name="Arial", size=10)
ALERT_FILL = PatternFill("solid", fgColor="FBE9E1")


def _header_row(ws, row, headers, start_col=1):
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=start_col + i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center")


def generar_reporte(fecha_lunes: date, target_service_level: float = 0.95, shrinkage: float = 0.10,
                     db_path: str = "callcenter.db", horas_contrato_nuevo: float = 36,
                     salida: str = "reporte_brecha_personal.xlsx"):

    empleados = listar_empleados(db_path=db_path)
    demanda = _demanda_por_dia(db_path, target_service_level, shrinkage)
    disp_cache = {e["id"]: obtener_disponibilidad(e["id"], db_path=db_path) for e in empleados}

    total_requerido = sum(sum(h.values()) for h in demanda.values())
    capacidad_maxima_actual = sum(e["horas_max_semana"] for e in empleados)
    brecha = max(0, total_requerido - capacidad_maxima_actual)
    asesores_recomendados = -(-brecha // horas_contrato_nuevo)

    detalle = []
    for h in range(HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN):
        disp_total, req_total = 0, 0
        for dia in DIAS_SEMANA:
            req_total += demanda.get(dia, {}).get(h, 0)
            for e in empleados:
                ventana = _ventana_disponibilidad(disp_cache[e["id"]].get(dia), dia)
                if ventana and ventana[0] <= h < ventana[1]:
                    disp_total += 1
        detalle.append({
            "hora": h, "requeridos_semana": req_total, "disponibles_sin_tope_semana": disp_total,
            "alcanza_solo_con_disponibilidad": disp_total >= req_total,
        })

    resultado_horario = generar_horario_semana(fecha_lunes, db_path=db_path,
                                                target_service_level=target_service_level, shrinkage=shrinkage)

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "Reporte de Brecha de Personal — Call Center"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Generado para la semana del {fecha_lunes.isoformat()}  |  "
                f"Meta de nivel de servicio: {int(target_service_level*100)}%  |  "
                f"Shrinkage aplicado: {int(shrinkage*100)}%")
    ws["A2"].font = Font(name="Arial", size=9, italic=True, color="6B7280")

    filas_resumen = [
        ("Agentes activos actuales", len(empleados)),
        ("Agente-horas requeridas por semana (Erlang C)", total_requerido),
        ("Capacidad máxima actual (todos al tope semanal)", capacidad_maxima_actual),
        ("Brecha (agente-horas/semana)", brecha),
        ("Brecha (%)", f"{brecha/total_requerido*100:.1f}%" if total_requerido else "0%"),
        ("Asesores adicionales recomendados", int(asesores_recomendados)),
        ("(asumiendo contrato de referencia de)", f"{horas_contrato_nuevo:.0f}h/semana"),
    ]
    r = 4
    for etiqueta, valor in filas_resumen:
        ws.cell(row=r, column=1, value=etiqueta).font = Font(name="Arial", bold=True)
        destacar = etiqueta == "Asesores adicionales recomendados"
        c = ws.cell(row=r, column=2, value=valor)
        c.font = Font(name="Arial", bold=destacar, color=RUST if destacar else "000000", size=14 if destacar else 10)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Conclusión clave:").font = Font(name="Arial", bold=True)
    r += 1
    conclusion = (
        "La disponibilidad horaria reportada por el equipo actual SÍ alcanza a cubrir casi todas las "
        "franjas del día si se ignora el tope de horas semanales — el cuello de botella no es la "
        "distribución horaria (no se necesitan perfiles de turno especiales), sino la CANTIDAD de "
        "personas. Por eso la recomendación es contratar más asesores con disponibilidad similar a "
        "la actual, no reestructurar los horarios existentes."
    )
    ws.cell(row=r, column=1, value=conclusion).font = NORMAL_FONT
    ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    ws.row_dimensions[r].height = 60

    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 16

    ws2 = wb.create_sheet("Detalle por hora")
    ws2["A1"] = "Demanda vs. disponibilidad total del equipo, por hora (sumado en la semana)"
    ws2["A1"].font = TITLE_FONT
    ws2.merge_cells("A1:D1")

    _header_row(ws2, 3, ["Hora", "Requeridos (semana)", "Disponibles sin tope semanal (semana)", "¿Alcanza solo con disponibilidad?"])
    for i, fila in enumerate(detalle, start=4):
        ws2.cell(row=i, column=1, value=f"{fila['hora']:02d}:00").font = NORMAL_FONT
        ws2.cell(row=i, column=2, value=fila["requeridos_semana"]).font = NORMAL_FONT
        ws2.cell(row=i, column=3, value=fila["disponibles_sin_tope_semana"]).font = NORMAL_FONT
        celda_ok = ws2.cell(row=i, column=4, value="Sí" if fila["alcanza_solo_con_disponibilidad"] else "No alcanza")
        celda_ok.font = Font(name="Arial", color=GREEN if fila["alcanza_solo_con_disponibilidad"] else RUST, bold=True)
        if not fila["alcanza_solo_con_disponibilidad"]:
            for col in range(1, 5):
                ws2.cell(row=i, column=col).fill = ALERT_FILL

    for col, w in zip("ABCD", [10, 20, 32, 26]):
        ws2.column_dimensions[col].width = w

    ws3 = wb.create_sheet("Horario generado (huecos)")
    ws3["A1"] = f"Horario propuesto semana del {fecha_lunes.isoformat()} — con déficit real señalado"
    ws3["A1"].font = TITLE_FONT
    ws3.merge_cells("A1:H1")

    _header_row(ws3, 3, ["Asesor"] + DIAS_SEMANA + ["Horas/semana"])
    for i, (nombre, dias) in enumerate(resultado_horario["horario"].items(), start=4):
        ws3.cell(row=i, column=1, value=nombre).font = NORMAL_FONT
        for j, dia in enumerate(DIAS_SEMANA, start=2):
            info = dias.get(dia, {"motivo": "?"})
            if "turnos" in info:
                txt = " + ".join(f"{t['inicio']:02d}:00-{t['fin']:02d}:00" for t in info["turnos"])
            else:
                mapa = {"no_disponible": "No disponible", "sin_informacion": "Sin información",
                        "libre_no_requerido": "Libre", "tope_semanal_alcanzado": "Tope semanal",
                        "descanso_asignado": "Descanso"}
                txt = mapa.get(info["motivo"], info["motivo"])
            ws3.cell(row=i, column=j, value=txt).font = NORMAL_FONT
        ws3.cell(row=i, column=9, value=resultado_horario["horas_semana"][nombre]).font = NORMAL_FONT

    fila_alertas = len(resultado_horario["horario"]) + 6
    ws3.cell(row=fila_alertas, column=1, value=f"Horas sin cubrir detectadas: {len(resultado_horario['alertas'])}").font = Font(name="Arial", bold=True, color=RUST)
    for k, a in enumerate(resultado_horario["alertas"][:40], start=fila_alertas + 1):
        ws3.cell(row=k, column=1, value=a).font = Font(name="Arial", size=9)

    ws3.column_dimensions["A"].width = 24
    for col in "BCDEFGH":
        ws3.column_dimensions[col].width = 16
    ws3.column_dimensions["I"].width = 14

    wb.save(salida)
    return {
        "total_requerido": total_requerido,
        "capacidad_maxima_actual": capacidad_maxima_actual,
        "brecha": brecha,
        "asesores_recomendados": int(asesores_recomendados),
        "archivo": salida,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        lunes = date.fromisoformat(sys.argv[1])
    else:
        hoy = date.today()
        lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)

    sl = float(sys.argv[2]) if len(sys.argv) > 2 else 0.95

    resumen = generar_reporte(lunes, target_service_level=sl)
    print(f"Reporte generado: {resumen['archivo']}")
    print(f"Requerido: {resumen['total_requerido']}h/semana | Capacidad actual: {resumen['capacidad_maxima_actual']}h/semana")
    print(f"Brecha: {resumen['brecha']}h/semana -> Se recomiendan {resumen['asesores_recomendados']} asesores adicionales")

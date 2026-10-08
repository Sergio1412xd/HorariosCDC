"""
Carga en el Historial (tu callcenter.db local) el horario que quedó en el PDF del
2026-09-14, tal como se generó (con turnos exactos), recalculando la cobertura real
con el modelo de demanda de ese día.

CÓMO USARLO:
1. Copia este archivo a la carpeta de tu proyecto (donde está main.py, db.py, etc.)
2. Abre una terminal en esa carpeta
3. Corre:  py cargar_horario_pdf.py
4. Recarga la pestaña "Historial" en el navegador -- debería aparecer la semana del
   2026-09-14 en la lista.

Es seguro correrlo más de una vez: si ya existe un registro para esa semana, lo
reemplaza (igual que "Guardar en el Historial" desde la app).
"""
import re
from datetime import date

from db import DIAS_SEMANA
from generador_horarios import generar_horario_semana, estimar_nivel_servicio_real
from costos import calcular_costo_horario
import db

FECHA_LUNES = "2026-09-14"
TARGET_SL = 0.85
SHRINKAGE = 0.10

# Roster tal cual aparece en el PDF que compartiste
ROSTER_TEXTO = {
    "OVER LUIS SIBAJA": ["11-17h", "12-21h (alm. 16-17h)", "11-15h", "Descanso", "11-15h", "11-17h", "11-17h"],
    "GINNETH MOYA": ["Descanso", "Tope sem.", "11-17h", "12-21h (alm. 16-17h)", "12-21h (alm. 16-17h)", "13-22h (alm. 15-16h)", "11-17h"],
    "SANTIAGO MOJICA": ["17-21h", "12-21h (alm. 16-17h)", "Descanso", "11-17h", "11-15h", "11-15h", "12-18h"],
    "YULIETH GALVIS": ["11-17h", "11-20h (alm. 15-16h)", "17-21h", "12-21h (alm. 17-18h)", "Descanso", "18-22h", "12-18h"],
    "JENNIFER VALENTIN": ["No disp.", "17-21h", "11-17h", "No disp.", "18-22h", "11-16h", "11-17h"],
    "JOHNNY ENSUNCHO": ["17-21h", "Descanso", "17-21h", "17-21h", "18-22h", "18-22h", "17-21h"],
    "SAMUEL BENITEZ": ["17-21h", "12-21h (alm. 15-16h)", "No disp.", "Libre", "13-22h (alm. 15-16h)", "14-22h (alm. 16-17h)", "11-17h"],
    "VANESSA ESPITIA": ["17-21h", "12-21h (alm. 17-18h)", "11-15h", "11-17h", "11-20h (alm. 17-18h)", "Descanso", "11-17h"],
    "FELIPE AYA": ["11-17h", "17-21h", "17-21h", "Descanso", "11-20h (alm. 15-16h)", "12-20h (alm. 16-17h)", "13-21h (alm. 17-18h)"],
    "HARRISON CORREA": ["No disp.", "No disp.", "No disp.", "No disp.", "12-21h (alm. 16-17h)", "13-22h (alm. 17-18h)", "13-21h (alm. 16-17h)"],
    "JUAN DAVID PABA": ["17-21h", "17-21h", "No disp.", "17-21h", "18-22h", "11-15h", "13-21h (alm. 17-18h)"],
    "JUAN DAVID GUZMAN": ["No disp.", "No disp.", "No disp.", "No disp.", "14-22h (alm. 17-18h)", "12-20h (alm. 15-16h)", "11-17h"],
    "GABRIEL BARRERA": ["Descanso", "11-15h", "11-17h", "12-21h (alm. 15-16h)", "11-20h (alm. 15-16h)", "11-15h", "11-17h"],
    "MARLON FLAUTERO": ["11-17h", "11-17h", "11-17h", "11-15h", "Descanso", "13-22h (alm. 16-17h)", "12-18h"],
    "JUAN CAMILO CADENA": ["11-17h", "11-17h", "Descanso", "11-15h", "Libre", "11-17h", "13-21h (alm. 16-17h)"],
    "NICOLAS MATEO ANTONIO": ["No disp.", "No disp.", "17-21h", "11-15h", "14-22h (alm. 15-16h)", "13-22h (alm. 16-17h)", "13-21h (alm. 15-16h)"],
    "PAULA OLAYA": ["11-15h", "Descanso", "17-21h", "17-21h", "11-20h (alm. 16-17h)", "14-22h (alm. 17-18h)", "13-21h (alm. 15-16h)"],
}

MOTIVOS = {
    "Descanso": "descanso_asignado", "No disp.": "no_disponible",
    "Libre": "libre_no_requerido", "Tope sem.": "tope_semanal_alcanzado",
}


def _parsear_celda(texto):
    if texto in MOTIVOS:
        return {"motivo": MOTIVOS[texto]}
    m = re.match(r"(\d+)-(\d+)h(?:\s*\(alm\.\s*(\d+)-(\d+)h\))?", texto)
    if not m:
        raise ValueError(f"No pude interpretar la celda: {texto!r}")
    inicio, fin, alm_inicio, alm_fin = m.groups()
    turno = {"inicio": int(inicio), "fin": int(fin), "excepcion": False}
    if alm_inicio:
        turno["almuerzo_inicio"] = int(alm_inicio)
        turno["almuerzo_horas"] = int(alm_fin) - int(alm_inicio)
    return {"turnos": [turno]}


def reconstruir_horario():
    # Nombres del roster que puedan no existir exactamente en TU base (mayúsculas/tildes) --
    # si algún nombre no calza, avisa en vez de fallar en silencio.
    empleados_bd = {e["nombre"] for e in db.listar_empleados()}
    faltantes = [n for n in ROSTER_TEXTO if n not in empleados_bd]
    if faltantes:
        print("⚠️  Estos nombres del PDF no existen tal cual en tu base de Personal:")
        for n in faltantes:
            print("   -", n)
        print("   Sus turnos se guardarán igual, pero revisa que el nombre coincida exacto")
        print("   (mayúsculas/tildes) si quieres que aparezcan bien en el detalle.\n")

    esqueleto = generar_horario_semana(date.fromisoformat(FECHA_LUNES), target_service_level=TARGET_SL, shrinkage=SHRINKAGE)

    horario = {}
    for nombre, celdas in ROSTER_TEXTO.items():
        horario[nombre] = {}
        for i, dia in enumerate(DIAS_SEMANA):
            horario[nombre][dia] = _parsear_celda(celdas[i])

    cobertura = esqueleto["cobertura"]
    for dia in DIAS_SEMANA:
        for h in cobertura[dia]:
            cobertura[dia][h]["programados"] = 0
    for nombre, dias in horario.items():
        for dia, info in dias.items():
            if "turnos" in info:
                for t in info["turnos"]:
                    horas_efectivas = set(range(t["inicio"], t["fin"]))
                    if t.get("almuerzo_horas"):
                        horas_efectivas -= set(range(t["almuerzo_inicio"], t["almuerzo_inicio"] + t["almuerzo_horas"]))
                    for h in horas_efectivas:
                        if h in cobertura[dia]:
                            cobertura[dia][h]["programados"] += 1

    horas_semana = {}
    for nombre, dias in horario.items():
        total = 0
        for info in dias.values():
            if "turnos" in info:
                for t in info["turnos"]:
                    total += (t["fin"] - t["inicio"]) - t.get("almuerzo_horas", 0)
        horas_semana[nombre] = total

    alertas = []
    for dia in DIAS_SEMANA:
        for h, c in sorted(cobertura[dia].items()):
            if c["requeridos"] > 0 and c["programados"] < c["requeridos"]:
                alertas.append(f"{dia} {h}:00 -- faltan {c['requeridos'] - c['programados']} asesor(es)")

    return {"horario": horario, "cobertura": cobertura, "alertas": alertas, "horas_semana": horas_semana}


if __name__ == "__main__":
    resultado = reconstruir_horario()
    costo = calcular_costo_horario(resultado)
    nivel_servicio = estimar_nivel_servicio_real(resultado)

    print("SL semana reconstruido:", nivel_servicio["sl_estimado_semana_pct"], "% (tu PDF decía 95.1%)")
    print("Costo semana reconstruido: $", f"{costo['total_semana']:,.0f}", "(tu PDF decía $10,118,040)")
    print("Horas-persona:", round(sum(resultado["horas_semana"].values())), "(tu PDF decía 527h)")
    print()

    horario_json = {}
    for nombre, dias in resultado["horario"].items():
        horario_json[nombre] = {}
        for dia, info in dias.items():
            if "turnos" in info:
                horario_json[nombre][dia] = {"tipo": "turno", "turnos": info["turnos"]}
            else:
                horario_json[nombre][dia] = {"tipo": "libre", "motivo": info["motivo"]}
    cobertura_json = {
        dia: [{"hora": h, "requeridos": c["requeridos"], "programados": c["programados"]}
              for h, c in horas.items()]
        for dia, horas in resultado["cobertura"].items()
    }
    horas_trabajadas = [h for h in resultado["horas_semana"].values() if h > 0]
    promedio_horas = round(sum(horas_trabajadas) / len(horas_trabajadas), 1) if horas_trabajadas else 0

    resultado_serializado = {
        "horario": horario_json, "cobertura": cobertura_json, "alertas": resultado["alertas"],
        "horas_semana": resultado["horas_semana"], "promedio_horas_por_asesor": promedio_horas,
        "costo": costo, "nivel_servicio": nivel_servicio,
    }
    parametros = {"target_service_level": TARGET_SL, "shrinkage": SHRINKAGE,
                  "max_occupancy": 0.85, "semanas_base": None, "reconstruido_desde_pdf": True}

    db.guardar_horario_generado(FECHA_LUNES, "sergio.ortiz (reconstruido desde PDF)", parametros, resultado_serializado)
    print(f"✅ Guardado en el Historial para la semana del {FECHA_LUNES}")
    print("   Recarga la pestaña Historial en el navegador para verlo.")

"""
loader_disponibilidad.py
Lee un archivo Excel con el formato:
    Asesor | Lunes | Martes | Miércoles | Jueves | Viernes | Sábado | Domingo
Donde cada celda es:
    - "Completa"          -> disponible todo el horario operativo
    - "No disponible"     -> no trabaja ese día
    - "Sin información"   -> falta el dato, requiere seguimiento (se marca para revisión)
    - "HH:MM - HH:MM"     -> disponible solo en ese rango

E inserta/actualiza empleados + su disponibilidad en la base de datos.
"""

import re
import pandas as pd

from db import init_db, crear_empleado, listar_empleados, set_disponibilidad, actualizar_empleado, DIAS_SEMANA

RANGO_REGEX = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")

# Nombres posibles que puede traer la columna de cédula según cómo la exportes
POSIBLES_COLUMNAS_CEDULA = ["Cédula", "Cedula", "CC", "Número de Cédula", "Numero de Cedula", "Documento"]


def _columna_cedula(df) -> str | None:
    for col in POSIBLES_COLUMNAS_CEDULA:
        if col in df.columns:
            return col
    return None


def interpretar_celda(valor: str):
    """Devuelve (tipo, hora_inicio, hora_fin) a partir del texto de la celda."""
    if pd.isna(valor):
        return "sin_informacion", None, None

    v = str(valor).strip()
    low = v.lower()

    if low == "completa":
        return "completa", None, None
    if low in ("no disponible", "no_disponible"):
        return "no_disponible", None, None
    if low in ("sin información", "sin informacion"):
        return "sin_informacion", None, None

    m = RANGO_REGEX.match(v)
    if m:
        return "rango", m.group(1), m.group(2)

    # Cualquier otro texto no reconocido: se marca para revisión manual en vez de fallar silenciosamente
    return "sin_informacion", None, None


def cargar_disponibilidad_excel(path: str, db_path: str = "callcenter.db", hoja: int = 0) -> dict:
    """
    Carga el archivo y devuelve un resumen: cuántos empleados se crearon,
    cuántas celdas quedaron como 'sin_informacion' (para que las revises).
    """
    init_db(db_path)
    df = pd.read_excel(path, sheet_name=hoja)

    # La primera columna suele ser un índice sin nombre ("Unnamed: 0"); la ignoramos.
    columnas_dias = [d for d in DIAS_SEMANA if d in df.columns]
    faltantes = [d for d in DIAS_SEMANA if d not in df.columns]
    if faltantes:
        raise ValueError(f"El archivo no tiene las columnas de estos días: {faltantes}")
    if "Asesor" not in df.columns:
        raise ValueError("El archivo debe tener una columna llamada 'Asesor'")

    col_cedula = _columna_cedula(df)

    empleados_existentes = {e["nombre"]: e["id"] for e in listar_empleados(solo_activos=False, db_path=db_path)}

    creados = 0
    reutilizados = 0
    celdas_sin_info = []
    sin_cedula = []

    for _, fila in df.iterrows():
        nombre = str(fila["Asesor"]).strip()
        if not nombre or nombre.lower() == "nan":
            continue

        cedula = None
        if col_cedula and not pd.isna(fila[col_cedula]):
            cedula = str(fila[col_cedula]).strip()
            # Evita que pandas convierta la cédula a notación tipo "12345.0"
            if cedula.endswith(".0"):
                cedula = cedula[:-2]

        if nombre in empleados_existentes:
            empleado_id = empleados_existentes[nombre]
            reutilizados += 1
            if cedula:
                actualizar_empleado(empleado_id, db_path=db_path, cedula=cedula)
        else:
            empleado_id = crear_empleado(nombre, cedula=cedula, db_path=db_path)
            empleados_existentes[nombre] = empleado_id
            creados += 1

        if not cedula:
            sin_cedula.append(nombre)

        for dia in columnas_dias:
            tipo, hi, hf = interpretar_celda(fila[dia])
            set_disponibilidad(empleado_id, dia, tipo, hi, hf, db_path=db_path)
            if tipo == "sin_informacion":
                celdas_sin_info.append((nombre, dia))

    return {
        "empleados_creados": creados,
        "empleados_actualizados": reutilizados,
        "celdas_sin_informacion": celdas_sin_info,
        "sin_cedula": sin_cedula,
        "columna_cedula_encontrada": col_cedula,
    }


if __name__ == "__main__":
    import sys

    # Uso:
    #   py loader_disponibilidad.py                          -> busca "Disponibilidad_de_horarios.xlsx" en esta misma carpeta
    #   py loader_disponibilidad.py "ruta\a\tu\archivo.xlsx"  -> usa la ruta que le pases
    ruta_archivo = sys.argv[1] if len(sys.argv) > 1 else "Disponibilidad_de_horarios.xlsx"

    resumen = cargar_disponibilidad_excel(ruta_archivo, db_path="callcenter.db")

    print("Empleados creados:", resumen["empleados_creados"])
    print("Empleados actualizados:", resumen["empleados_actualizados"])

    if resumen["columna_cedula_encontrada"]:
        print(f"\nColumna de cédula detectada: '{resumen['columna_cedula_encontrada']}'")
    else:
        print("\n⚠ No se encontró columna de cédula en el archivo (se buscó: "
              f"{POSIBLES_COLUMNAS_CEDULA}). Puedes agregarla al Excel y volver a correr "
              "este script, o cargar la cédula manualmente desde la interfaz web.")

    if resumen["sin_cedula"]:
        print(f"\nAsesores sin cédula registrada ({len(resumen['sin_cedula'])}):")
        for n in resumen["sin_cedula"]:
            print(f"  - {n}")

    print("\nCeldas marcadas 'Sin información' (necesitan seguimiento con el asesor):")
    for nombre, dia in resumen["celdas_sin_informacion"]:
        print(f"  - {nombre}: {dia}")

"""
loader_llamadas.py
Lee tu archivo de llamadas (columnas: Número, Campaña, Fecha, Hora, Espera (s),
Duración (s), Agente, Resultado) y lo inserta en la tabla 'llamadas'.

DISEÑADO PARA CARGA INCREMENTAL / SEMANAL:
Cada llamada se identifica con un hash único basado en (Número, Fecha, Hora, Agente, Resultado).
Si vuelves a subir un archivo que incluye llamadas que ya estaban cargadas (ej. subes el
acumulado del mes completo cada semana), el sistema las detecta y las IGNORA — nunca se
duplican ni se suman dos veces. Con el tiempo vas acumulando historial real (agosto,
septiembre, octubre...) sin importar si los archivos que subes se solapan entre sí.

Uso:
    py loader_llamadas.py                              -> busca "llamadas_agosto.xlsx" en esta carpeta
    py loader_llamadas.py "ruta\\a\\tu\\archivo.xlsx"     -> usa la ruta que le pases
"""

import hashlib
import sys

import pandas as pd

from db import init_db, insertar_llamadas_bulk, rango_fechas_llamadas

COLUMNAS_ESPERADAS = ["Número", "Campaña", "Fecha", "Hora", "Espera (s)", "Duración (s)", "Agente", "Resultado"]


def _parsear_hora(valor: str) -> str:
    """Convierte '11:01:29 a. m.' / '2:15:00 p. m.' a 'HH:MM:SS' de 24 horas."""
    texto = str(valor).strip()
    texto = (texto.replace("a. m.", "AM").replace("p. m.", "PM")
                   .replace("a.m.", "AM").replace("p.m.", "PM")
                   .replace("a. m", "AM").replace("p. m", "PM"))
    t = pd.to_datetime(texto, format="%I:%M:%S %p").time()
    return t.strftime("%H:%M:%S")


def _calcular_hash(numero, fecha, hora, agente, resultado) -> str:
    base = f"{numero}|{fecha}|{hora}|{agente}|{resultado}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def cargar_llamadas_excel(path: str, db_path: str = "callcenter.db", hoja: int = 0) -> dict:
    init_db(db_path)
    df = pd.read_excel(path, sheet_name=hoja)

    faltantes = [c for c in COLUMNAS_ESPERADAS if c not in df.columns]
    if faltantes:
        raise ValueError(f"Al archivo le faltan estas columnas: {faltantes}")

    filas = []
    errores_hora = 0

    for _, fila in df.iterrows():
        try:
            hora_str = _parsear_hora(fila["Hora"])
        except Exception:
            errores_hora += 1
            continue

        fecha_str = pd.to_datetime(fila["Fecha"]).strftime("%Y-%m-%d")
        numero = None if pd.isna(fila["Número"]) else str(fila["Número"])
        agente = None if pd.isna(fila["Agente"]) else str(fila["Agente"]).strip()
        espera = None if pd.isna(fila["Espera (s)"]) else float(fila["Espera (s)"])
        duracion = None if pd.isna(fila["Duración (s)"]) else float(fila["Duración (s)"])
        resultado = str(fila["Resultado"]).strip()
        campana = str(fila["Campaña"]).strip()

        filas.append({
            "numero": numero,
            "campana": campana,
            "fecha": fecha_str,
            "hora": hora_str,
            "espera_seg": espera,
            "duracion_seg": duracion,
            "agente": agente,
            "resultado": resultado,
            "hash_unico": _calcular_hash(numero, fecha_str, hora_str, agente, resultado),
        })

    resultado_insercion = insertar_llamadas_bulk(filas, db_path=db_path)
    resultado_insercion["filas_leidas"] = len(df)
    resultado_insercion["errores_hora"] = errores_hora
    resultado_insercion["rango_total_bd"] = rango_fechas_llamadas(db_path=db_path)
    return resultado_insercion


if __name__ == "__main__":
    ruta_archivo = sys.argv[1] if len(sys.argv) > 1 else "llamadas_agosto.xlsx"

    resumen = cargar_llamadas_excel(ruta_archivo)

    print(f"Filas leídas del archivo:      {resumen['filas_leidas']}")
    print(f"Llamadas NUEVAS insertadas:    {resumen['insertadas_nuevas']}")
    print(f"Llamadas que ya existían:      {resumen['ya_existian']} (ignoradas, sin duplicar)")
    if resumen["errores_hora"]:
        print(f"⚠ Filas con hora no reconocida (omitidas): {resumen['errores_hora']}")

    rango = resumen["rango_total_bd"]
    print(f"\nHistórico total acumulado en la base de datos:")
    print(f"  Desde {rango['mn']} hasta {rango['mx']}  ({rango['c']} llamadas en total)")

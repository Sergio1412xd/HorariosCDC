"""
migrar_a_turso.py
Sube tu callcenter.db actual (con tus empleados, horarios, usuarios, auditoría,
etc. ya cargados) a una base de datos nueva en Turso, lista para usar con
TURSO_DATABASE_URL / TURSO_AUTH_TOKEN en Render.

No necesitas instalar el CLI de Turso (en Windows pide WSL, y ya vimos que tu
PC bloquea instaladores) — esto solo usa Python + la librería 'requests',
hablando directo con la API de Turso.

QUÉ NECESITAS ANTES DE CORRERLO (ambos 100% desde el navegador, sin instalar nada):

1. Un "API Token" de Turso (de cuenta/organización, no de una base específica):
   entra a https://app.turso.tech -> ícono de tu cuenta (arriba a la derecha)
   -> "Account Settings" -> "API Tokens" -> "Create Token". Cópialo.

2. El "slug" de tu organización: aparece en la URL del dashboard, algo como
   https://app.turso.tech/TU-ORGANIZACION/... -> "TU-ORGANIZACION" es el slug.
   Si nunca creaste una organización, Turso te pone una personal automática
   (usualmente tu usuario) — ahí mismo la ves.

CÓMO CORRERLO:

   py migrar_a_turso.py --token TU_API_TOKEN --org TU_ORGANIZACION --db-file callcenter.db

Al final te imprime el TURSO_DATABASE_URL y el TURSO_AUTH_TOKEN listos para
pegar en las variables de entorno de Render. Nunca toca tu callcenter.db
original — trabaja sobre una copia temporal.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile

try:
    import requests
except ImportError:
    print("Falta la librería 'requests'. Instálala con:\n  py -m pip install requests --break-system-packages")
    sys.exit(1)

API_BASE = "https://api.turso.tech/v1"


def preparar_copia_wal(db_file: str) -> str:
    """Copia el .db a un archivo temporal y lo deja en modo WAL con el WAL
    'aplastado' dentro del archivo principal — requisito de Turso para
    poder subirlo. Nunca toca el archivo original."""
    tmp_dir = tempfile.mkdtemp(prefix="migrar_turso_")
    copia = os.path.join(tmp_dir, "callcenter_para_turso.db")
    shutil.copy2(db_file, copia)

    con = sqlite3.connect(copia)
    modo = con.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    con.commit()
    con.close()

    if modo.lower() != "wal":
        print(f"⚠️  No se pudo confirmar modo WAL (SQLite devolvió '{modo}'). "
              f"Turso puede rechazar el archivo — si falla la subida, es la causa más probable.")
    else:
        print("✅ Copia preparada en modo WAL.")
    return copia


def crear_base_con_datos(token: str, org: str, nombre_db: str, grupo: str = "default"):
    print(f"-> Creando base '{nombre_db}' en Turso (org: {org})...")
    resp = requests.post(
        f"{API_BASE}/organizations/{org}/databases",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": nombre_db, "group": grupo, "seed": {"type": "database_upload"}},
        timeout=30,
    )
    if resp.status_code >= 300:
        print(f"❌ Turso respondió {resp.status_code} al crear la base:\n{resp.text}")
        if "group" in resp.text.lower():
            print("   Pista: si tu organización no tiene un grupo llamado 'default', "
                  "dime cómo se llama el tuyo (aparece en el dashboard) y lo ajustamos.")
        sys.exit(1)
    data = resp.json()
    hostname = data["database"]["Hostname"]
    print(f"✅ Base creada. Hostname: {hostname}")
    return hostname


def crear_token_db(token: str, org: str, nombre_db: str) -> str:
    print(f"-> Generando token de acceso para '{nombre_db}'...")
    resp = requests.post(
        f"{API_BASE}/organizations/{org}/databases/{nombre_db}/auth/tokens",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code >= 300:
        print(f"❌ Turso respondió {resp.status_code} al crear el token:\n{resp.text}")
        sys.exit(1)
    jwt = resp.json()["jwt"]
    print("✅ Token generado.")
    return jwt


def subir_archivo(hostname: str, db_token: str, archivo: str):
    print(f"-> Subiendo {archivo} a https://{hostname}/v1/upload ...")
    tamano = os.path.getsize(archivo)
    with open(archivo, "rb") as f:
        resp = requests.post(
            f"https://{hostname}/v1/upload",
            headers={
                "Authorization": f"Bearer {db_token}",
                "Content-Length": str(tamano),
            },
            data=f,
            timeout=120,
        )
    if resp.status_code >= 300:
        print(f"❌ Turso respondió {resp.status_code} al subir el archivo:\n{resp.text}")
        print("   Causas típicas: el archivo no quedó en modo WAL (ver aviso arriba), "
              "o la base ya tenía datos de un intento previo (usa un --nombre-db distinto).")
        sys.exit(1)
    print("✅ Archivo subido y cargado en Turso.")


def main():
    ap = argparse.ArgumentParser(description="Migra tu callcenter.db local a una base nueva en Turso.")
    ap.add_argument("--token", required=True, help="API Token de tu cuenta Turso (Account Settings -> API Tokens)")
    ap.add_argument("--org", required=True, help="Slug de tu organización Turso (aparece en la URL del dashboard)")
    ap.add_argument("--db-file", default="callcenter.db", help="Ruta a tu callcenter.db (por defecto: callcenter.db)")
    ap.add_argument("--nombre-db", default="horarios-cdc", help="Nombre para la base nueva en Turso (por defecto: horarios-cdc)")
    ap.add_argument("--grupo", default="default", help="Grupo de Turso donde crear la base (por defecto: default)")
    args = ap.parse_args()

    # Si alguien pega la URL completa del dashboard en --org (fácil de hacer,
    # ya pasó), nos quedamos solo con el slug en vez de fallar con un 404 raro.
    org_original = args.org
    args.org = args.org.strip().removeprefix("https://").removeprefix("http://")
    args.org = args.org.removeprefix("app.turso.tech/").strip("/")
    if args.org != org_original.strip():
        print(f"ℹ️  Interpretando --org '{org_original}' como el slug '{args.org}'.")

    if not os.path.exists(args.db_file):
        print(f"❌ No encuentro el archivo: {args.db_file}")
        sys.exit(1)

    copia = preparar_copia_wal(args.db_file)
    hostname = crear_base_con_datos(args.token, args.org, args.nombre_db, args.grupo)
    db_token = crear_token_db(args.token, args.org, args.nombre_db)
    subir_archivo(hostname, db_token, copia)

    print("\n" + "=" * 70)
    print("LISTO — pega esto en las variables de entorno de tu servicio en Render:")
    print("=" * 70)
    print(f"TURSO_DATABASE_URL = libsql://{hostname}")
    print(f"TURSO_AUTH_TOKEN   = {db_token}")
    print("=" * 70)
    print("\nGuarda ese token en un lugar seguro — es la llave completa a tu base de datos.")


if __name__ == "__main__":
    main()

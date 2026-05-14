"""
resync_historico.py
-------------------
Descarga TODAS las carreras de Strava desde el principio,
incluyendo FC, calorías y ciudad para cada actividad.
Hace un backup de la BD antes de recrearla.
Al finalizar regenera el dashboard.
"""
import os, sys

# Fix SSL cert verification en Python 3.14 Windows
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE",       certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE",  certifi.where())
except ImportError:
    pass

import requests
import sqlite3
import shutil
import subprocess
from datetime import datetime

sys.path.insert(0, r"D:\BackUp Emi\Code\StravaApi")
import config

DASHBOARD_DIR = r"D:\BackUp Emi\Code\StravaApi"

def get_token():
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": config.REFRESH_TOKEN
    })
    data = r.json()
    if "access_token" not in data:
        print(f"Error al obtener token: {data}")
        sys.exit(1)
    return data["access_token"]

def fetch_all_runs(token):
    print("Descargando actividades de Strava (esto puede tardar un minuto)...")
    runs = []
    page = 1
    while True:
        r = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 200, "page": page}
        )
        if r.status_code == 429:
            print("  Rate limit alcanzado, espera 15 minutos e intenta de nuevo.")
            sys.exit(1)
        data = r.json()
        if not data or not isinstance(data, list):
            break
        page_runs = [a for a in data if a.get("type") == "Run"]
        runs.extend(page_runs)
        total = len(data)
        print(f"  Página {page:>3}: {total:>3} actividades  |  {len(page_runs):>3} carreras  |  acumulado: {len(runs)}")
        if total < 200:
            break
        page += 1
    return runs

def resync():
    # 1. Backup de la BD actual
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config.DB_PATH.replace(".db", f"_backup_{ts}.db")
    shutil.copy2(config.DB_PATH, backup)
    print(f"Backup creado: {backup}\n")

    # 2. Token Strava
    token = get_token()

    # 3. Descargar todas las carreras
    runs = fetch_all_runs(token)
    print(f"\nTotal carreras descargadas de Strava: {len(runs)}\n")

    # 4. Recrear tabla con esquema completo
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("DROP TABLE IF EXISTS carreras")
    conn.execute("""
        CREATE TABLE carreras (
            id            INTEGER PRIMARY KEY,
            fecha         TEXT,
            nombre        TEXT,
            distancia_km  REAL,
            tiempo_min    REAL,
            ritmo_min_km  REAL,
            velocidad_kmh REAL,
            desnivel_m    REAL,
            fc_media      REAL,
            fc_max        REAL,
            calorias      REAL,
            ciudad        TEXT,
            polyline      TEXT
        )
    """)

    # 5. Insertar todas las actividades
    insertadas = 0
    con_fc = 0
    sin_fc = 0

    for a in runs:
        dist_km = a["distance"] / 1000
        if dist_km <= 0:
            continue
        mov_min = a["moving_time"] / 60
        ritmo   = mov_min / dist_km
        vel     = dist_km / (a["moving_time"] / 3600) if a["moving_time"] > 0 else 0
        fc      = a.get("average_heartrate")

        conn.execute("""
            INSERT OR REPLACE INTO carreras
                (id, fecha, nombre, distancia_km, tiempo_min, ritmo_min_km,
                 velocidad_kmh, desnivel_m, fc_media, fc_max, calorias, ciudad, polyline)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a["id"],
            a["start_date_local"][:10],
            a.get("name", ""),
            round(dist_km, 4),
            round(mov_min, 2),
            round(ritmo, 4),
            round(vel, 2),
            a.get("total_elevation_gain", 0),
            fc,
            a.get("max_heartrate"),
            a.get("calories"),
            a.get("location_city") or "",
            (a.get("map") or {}).get("summary_polyline") or ""
        ))
        insertadas += 1
        if fc:
            con_fc += 1
        else:
            sin_fc += 1

    conn.commit()
    conn.close()

    print(f"Resincronizacion completa:")
    print(f"  Carreras insertadas : {insertadas}")
    print(f"  Con FC media        : {con_fc}")
    print(f"  Sin FC              : {sin_fc}")

    # 6. Regenerar dashboard
    print("\nRegenerando dashboard...")
    script = os.path.join(DASHBOARD_DIR, "generar_dashboard.py")
    result = subprocess.run([sys.executable, script], capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"Error al regenerar dashboard:\n{result.stderr.strip()}")
    else:
        print("Dashboard actualizado correctamente")

if __name__ == "__main__":
    resync()

"""
sync_strava.py  (versión repo — usada por GitHub Actions y Task Scheduler)
Descarga carreras nuevas desde Strava y las inserta en carreras.db.
NO llama a generar_dashboard.py — el llamador lo hace si quiere.
"""
import os
import sys

# Fix encoding para terminales cp1252 (emojis en Windows)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Fix SSL en Python 3.14 Windows (cert.pem ausente)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE",      certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import sqlite3
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import config


def get_token():
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": config.REFRESH_TOKEN,
    })
    data = r.json()
    if "access_token" not in data:
        print(f"ERROR token: {data}")
        sys.exit(1)
    return data["access_token"]


def init_db():
    """Crea tabla si no existe y migra columnas nuevas."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS carreras (
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
    columnas_nuevas = {
        "tiempo_min":    "REAL",
        "velocidad_kmh": "REAL",
        "fc_max":        "REAL",
        "calorias":      "REAL",
        "ciudad":        "TEXT",
        "polyline":      "TEXT",
    }
    existentes = {row[1] for row in conn.execute("PRAGMA table_info(carreras)")}
    for col, tipo in columnas_nuevas.items():
        if col not in existentes:
            conn.execute(f"ALTER TABLE carreras ADD COLUMN {col} {tipo}")
            print(f"  Columna '{col}' añadida")
    conn.commit()
    return conn


def get_last_date(conn):
    r = conn.execute("SELECT MAX(fecha) FROM carreras").fetchone()[0]
    return r or "2000-01-01"


def sync():
    print(f"DB: {config.DB_PATH}")
    token = get_token()
    conn  = init_db()
    last  = get_last_date(conn)
    print(f"Ultima carrera en BD: {last}")

    nuevas = 0
    page   = 1
    while True:
        r = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 100, "page": page},
        )
        if r.status_code == 429:
            print("Rate limit Strava — espera 15 min")
            sys.exit(1)
        data = r.json()
        if not data:
            break

        parar = False
        for a in data:
            if a.get("type") != "Run":
                continue
            fecha = a["start_date_local"][:10]
            if fecha <= last:
                parar = True
                continue
            dist_km = a["distance"] / 1000
            if dist_km <= 0:
                continue
            mov_min = a["moving_time"] / 60
            ritmo   = mov_min / dist_km
            vel     = dist_km / (a["moving_time"] / 3600) if a["moving_time"] > 0 else 0

            conn.execute("""
                INSERT OR IGNORE INTO carreras
                    (id, fecha, nombre, distancia_km, tiempo_min, ritmo_min_km,
                     velocidad_kmh, desnivel_m, fc_media, fc_max, calorias, ciudad, polyline)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                a["id"],
                fecha,
                a.get("name", ""),
                round(dist_km, 4),
                round(mov_min, 2),
                round(ritmo, 4),
                round(vel, 2),
                a.get("total_elevation_gain", 0),
                a.get("average_heartrate"),
                a.get("max_heartrate"),
                a.get("calories"),
                a.get("location_city") or "",
                (a.get("map") or {}).get("summary_polyline") or "",
            ))
            nuevas += 1

        if parar:
            break
        page += 1

    conn.commit()
    conn.close()
    print(f"{nuevas} carreras nuevas añadidas")


if __name__ == "__main__":
    sync()

import sqlite3
import csv
from datetime import datetime
import config

conn = sqlite3.connect(config.DB_PATH)
conn.execute("""
    CREATE TABLE IF NOT EXISTS carreras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        nombre TEXT,
        distancia_km REAL,
        ritmo_min_km REAL,
        desnivel_m REAL,
        fc_media REAL
    )
""")
conn.execute("DELETE FROM carreras")

imported = 0
skipped = 0
with open(config.CSV_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            dist = float(row['distancia_km'])
            pace = float(row['ritmo_min_km'])
            elev = float(row['total_elevation_gain'])
            if dist < 1.0 or not (3.0 <= pace <= 15.0):
                skipped += 1
                continue
            # Normalizar fecha a YYYY-MM-DD
            fecha = row['start_date_local'][:10]
            conn.execute(
                "INSERT INTO carreras (fecha, nombre, distancia_km, ritmo_min_km, desnivel_m, fc_media) VALUES (?,?,?,?,?,?)",
                (fecha, row['name'], dist, pace, elev, None)
            )
            imported += 1
        except Exception as e:
            skipped += 1

conn.commit()
conn.close()
print(f"Base de datos creada: {config.DB_PATH}")
print(f"  Importadas: {imported} carreras")
print(f"  Omitidas:   {skipped} registros")

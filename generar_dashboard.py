import sqlite3
import json
import os
import config
from datetime import date, timedelta


def decode_polyline_first(poly):
    """Devuelve (lat, lng) del primer punto de un Google Encoded Polyline."""
    if not poly:
        return None, None
    idx = 0
    vals = []
    for _ in range(2):
        shift = result = 0
        while idx < len(poly):
            b = ord(poly[idx]) - 63; idx += 1
            result |= (b & 0x1f) << shift; shift += 5
            if b < 0x20:
                break
        vals.append(~(result >> 1) if result & 1 else result >> 1)
    return round(vals[0] / 1e5, 5), round(vals[1] / 1e5, 5)

def fmt_pace(p):
    if p is None: return "--:--"
    m = int(p); s = int(round((p - m) * 60))
    return f"{m}:{s:02d}"

def fmt_time(dist, pace):
    total = dist * pace          # minutos decimales
    h = int(total // 60)
    m = int(total % 60)
    s = int(round((total - int(total)) * 60))
    return f"{h}h{m:02d}m{s:02d}s"

def diff_pct(a, b):
    """Variación porcentual de b respecto a a."""
    if not a or not b: return 0
    return round((b - a) / a * 100, 1)

def calc_streak(conn):
    rows = conn.execute("SELECT DISTINCT fecha FROM carreras ORDER BY fecha DESC").fetchall()
    weeks = set()
    for r in rows:
        d = date.fromisoformat(r[0])
        weeks.add(d.isocalendar()[:2])
    streak = 0
    current = date.today()
    while True:
        wk = current.isocalendar()[:2]
        if wk in weeks:
            streak += 1
            current -= timedelta(weeks=1)
        else:
            break
    return streak

conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row

# ── RESUMEN GLOBAL ──────────────────────────────────────────
stats = conn.execute("""
    SELECT COUNT(*) as total_carreras,
           ROUND(SUM(distancia_km),1) as km_totales,
           ROUND(AVG(distancia_km),2) as distancia_media,
           MIN(ritmo_min_km) as mejor_ritmo,
           AVG(ritmo_min_km) as ritmo_medio,
           ROUND(MAX(distancia_km),2) as max_distancia,
           ROUND(SUM(desnivel_m),0) as desnivel_total
    FROM carreras
""").fetchone()

# ── FORMA ACTUAL: últimas 4 sem vs anteriores 4 sem ─────────
forma_act = conn.execute("""
    SELECT COUNT(*) as n, ROUND(SUM(distancia_km),1) as km,
           AVG(ritmo_min_km) as ritmo, ROUND(AVG(distancia_km),1) as media
    FROM carreras WHERE fecha >= date('now','-28 days')
""").fetchone()

forma_prev = conn.execute("""
    SELECT COUNT(*) as n, ROUND(SUM(distancia_km),1) as km,
           AVG(ritmo_min_km) as ritmo, ROUND(AVG(distancia_km),1) as media
    FROM carreras WHERE fecha >= date('now','-56 days') AND fecha < date('now','-28 days')
""").fetchone()

racha = calc_streak(conn)

# Km/semana media últimas 4 semanas
km_sem_media = round((forma_act['km'] or 0) / 4, 1)

# Este mes vs mismo mes año anterior
mes_act = conn.execute("""
    SELECT COUNT(*) as n, ROUND(SUM(distancia_km),1) as km
    FROM carreras WHERE strftime('%Y-%m',fecha) = strftime('%Y-%m','now')
""").fetchone()

mes_prev_año = conn.execute("""
    SELECT COUNT(*) as n, ROUND(SUM(distancia_km),1) as km
    FROM carreras WHERE strftime('%m',fecha) = strftime('%m','now')
      AND strftime('%Y',fecha) = strftime('%Y',date('now','-1 year'))
""").fetchone()

# ── RECORDS PERSONALES ───────────────────────────────────────
pr_config = [
    ("5K",      4.5,  5.5),
    ("10K",     9.5,  10.5),
    ("Media",  19.0,  22.5),
    ("Maratón",40.0,  50.0),
]
prs = []
for label, dmin, dmax in pr_config:
    r = conn.execute("""
        SELECT fecha, nombre, distancia_km, ritmo_min_km
        FROM carreras WHERE distancia_km BETWEEN ? AND ?
        ORDER BY ritmo_min_km ASC LIMIT 1
    """, (dmin, dmax)).fetchone()
    if r:
        dias = (date.today() - date.fromisoformat(r['fecha'])).days
        años  = dias // 365; meses = (dias % 365) // 30
        if años > 0:   hace = f"hace {años}a {meses}m"
        elif meses > 0: hace = f"hace {meses} meses"
        else:           hace = f"hace {dias} días"
        prs.append({
            "dist": label, "fecha": r["fecha"],
            "nombre": r["nombre"][:40],
            "dist_km": round(r["distancia_km"], 2),
            "ritmo": fmt_pace(r["ritmo_min_km"]),
            "tiempo": fmt_time(r["distancia_km"], r["ritmo_min_km"]),
            "hace": hace, "dias": dias,
        })

# ── POR AÑO ──────────────────────────────────────────────────
por_año = conn.execute("""
    SELECT strftime('%Y',fecha) as año, COUNT(*) as carreras,
           ROUND(SUM(distancia_km),1) as km_totales,
           ROUND(AVG(distancia_km),2) as dist_media,
           AVG(ritmo_min_km) as ritmo_medio,
           MIN(ritmo_min_km) as mejor_ritmo
    FROM carreras GROUP BY año ORDER BY año
""").fetchall()

# ── MENSUAL últimos 24 meses ──────────────────────────────────
mensual = conn.execute("""
    SELECT strftime('%Y-%m',fecha) as mes, COUNT(*) as carreras,
           ROUND(SUM(distancia_km),1) as km_mes,
           AVG(ritmo_min_km) as ritmo_medio
    FROM carreras WHERE fecha >= date('now','-24 months')
    GROUP BY mes ORDER BY mes
""").fetchall()

# ── CARGA SEMANAL últimas 12 semanas ─────────────────────────
semanas = conn.execute("""
    SELECT strftime('%Y-%W',fecha) as semana,
           ROUND(SUM(distancia_km),1) as km,
           COUNT(*) as carreras,
           AVG(ritmo_min_km) as ritmo
    FROM carreras WHERE fecha >= date('now','-84 days')
    GROUP BY semana ORDER BY semana
""").fetchall()

# ── FC MEDIA ANUAL (sin límite de fecha para mostrar todo el histórico) ─
fc_anual = conn.execute("""
    SELECT strftime('%Y',fecha) as año,
           ROUND(AVG(fc_media),0) as fc,
           COUNT(*) as n
    FROM carreras WHERE fc_media IS NOT NULL AND fc_media > 0
    GROUP BY año ORDER BY año
""").fetchall()

# ── EFICIENCIA AERÓBICA mensual (velocidad m/min ÷ FC × 100) ─
eficiencia = conn.execute("""
    SELECT strftime('%Y-%m',fecha) as mes,
           ROUND(AVG(1000.0 / ritmo_min_km / fc_media * 100), 2) as ef
    FROM carreras
    WHERE fc_media IS NOT NULL AND fc_media > 0 AND distancia_km >= 5
      AND fecha >= date('now','-24 months')
    GROUP BY mes ORDER BY mes
""").fetchall()

# ── CONSISTENCIA: semanas activas por mes (últimos 13 meses) ─
consistencia = conn.execute("""
    SELECT strftime('%Y-%m',fecha) as mes,
           COUNT(DISTINCT strftime('%Y-%W',fecha)) as semanas,
           COUNT(*) as carreras,
           ROUND(SUM(distancia_km),1) as km
    FROM carreras WHERE fecha >= date('now','-13 months')
    GROUP BY mes ORDER BY mes
""").fetchall()

# ── TABLAS ────────────────────────────────────────────────────
ultimas = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, ritmo_min_km, desnivel_m, fc_media
    FROM carreras ORDER BY fecha DESC LIMIT 10
""").fetchall()

top_rapidas = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, ritmo_min_km
    FROM carreras WHERE distancia_km >= 5
    ORDER BY ritmo_min_km ASC LIMIT 5
""").fetchall()

top_largas = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, ritmo_min_km, desnivel_m
    FROM carreras ORDER BY distancia_km DESC LIMIT 5
""").fetchall()

maratones = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, ritmo_min_km
    FROM carreras WHERE distancia_km >= 40
    ORDER BY ritmo_min_km ASC
""").fetchall()

medias = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, ritmo_min_km
    FROM carreras WHERE distancia_km >= 19 AND distancia_km < 40
    ORDER BY ritmo_min_km ASC LIMIT 20
""").fetchall()

# ── PAÍSES ────────────────────────────────────────────────────
paises_keywords = {
    'AU': ['sydney','lane cove','port macquarie','wentworth','australia','melbourne','brisbane'],
    'GB': ['newcastle upon tyne','london','manchester','edinburgh','england','scotland'],
    'PT': ['lisbon','lisboa','porto','portugal'],
    'DE': ['berlin','münchen','frankfurt','hamburg','germany'],
    'FR': ['paris','lyon','marseille','france'],
    'IT': ['roma','rome','milan','milano','italy','italia'],
    'US': ['new york','chicago','boston','los angeles','usa'],
    'JP': ['tokyo','osaka','japan','japón'],
    'CH': ['geneva','bern','lausanne'],
}
paises_con_carreras = {'ES'}   # España siempre
for iso, kws in paises_keywords.items():
    clauses = " OR ".join(["LOWER(nombre) LIKE ?" for _ in kws])
    params  = [f"%{kw}%" for kw in kws]
    n = conn.execute(f"SELECT COUNT(*) FROM carreras WHERE {clauses}", params).fetchone()[0]
    if n > 0:
        paises_con_carreras.add(iso)

franjas_data = []
for label, cond in [("< 5 km","distancia_km < 5"),("5–8 km","distancia_km>=5 AND distancia_km<8"),
                    ("8–12 km","distancia_km>=8 AND distancia_km<12"),("12–17 km","distancia_km>=12 AND distancia_km<17"),
                    ("17–22 km","distancia_km>=17 AND distancia_km<22"),("> 22 km","distancia_km>=22")]:
    n = conn.execute(f"SELECT COUNT(*) as n FROM carreras WHERE {cond}").fetchone()["n"]
    franjas_data.append({"label": label, "n": n})

# ── TODAS LAS CARRERAS (para filtros dinámicos y detalle en JS) ──
all_runs_raw = conn.execute("""
    SELECT id, fecha, nombre, distancia_km, tiempo_min, ritmo_min_km, velocidad_kmh,
           COALESCE(desnivel_m,0) as desnivel_m, fc_media, fc_max, calorias,
           COALESCE(ciudad,'') as ciudad, COALESCE(polyline,'') as polyline
    FROM carreras ORDER BY fecha ASC
""").fetchall()

conn.close()

# ── HELPERS para tendencia ────────────────────────────────────
def trend_km(act, prev):
    if not prev or not prev['km']: return "", "#94a3b8"
    d = diff_pct(prev['km'], act['km'])
    if d >= 0: return f"+{d}%", "#22c55e"
    return f"{d}%", "#f97316"

def trend_pace(act, prev):
    """Ritmo menor = mejor, así que si baja es positivo."""
    if not prev or not prev['ritmo'] or not act['ritmo']: return "", "#94a3b8"
    d = diff_pct(prev['ritmo'], act['ritmo'])
    if d <= -1: return f"{d}% más rápido", "#22c55e"
    if d >= 1:  return f"+{d}% más lento", "#f97316"
    return "sin cambio", "#94a3b8"

tkm_color, tkm_txt = trend_km(forma_act, forma_prev)
trt_txt, trt_color = trend_pace(forma_act, forma_prev)

mes_km_diff, mes_km_color = trend_km(mes_act, mes_prev_año)

# ── JSON para JS ──────────────────────────────────────────────
años_l     = [r["año"]                      for r in por_año]
años_km    = [r["km_totales"]               for r in por_año]
años_ritmo = [round(r["ritmo_medio"],4)     for r in por_año]
años_carr  = [r["carreras"]                 for r in por_año]
años_rl    = [fmt_pace(r["ritmo_medio"])    for r in por_año]

mes_l      = [r["mes"]                      for r in mensual]
mes_km     = [r["km_mes"]                   for r in mensual]
mes_ritmo  = [round(r["ritmo_medio"],4)     for r in mensual]
mes_rl     = [fmt_pace(r["ritmo_medio"])    for r in mensual]

sem_l      = [r["semana"]                   for r in semanas]
sem_km     = [r["km"]                       for r in semanas]
sem_carr   = [r["carreras"]                 for r in semanas]

fc_l       = [r["año"]                      for r in fc_anual]
fc_v       = [r["fc"]                       for r in fc_anual]

ef_l       = [r["mes"]                      for r in eficiencia]
ef_v       = [r["ef"]                       for r in eficiencia]

cons_l     = [r["mes"]                      for r in consistencia]
cons_sem   = [r["semanas"]                  for r in consistencia]
cons_km    = [r["km"]                       for r in consistencia]

fl         = [f["label"]                    for f in franjas_data]
fc_counts  = [f["n"]                        for f in franjas_data]

ultimas_r  = [{"id":r["id"],"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
               "ritmo":fmt_pace(r["ritmo_min_km"]),"desnivel":int(r["desnivel_m"] or 0),
               "fc": int(r["fc_media"]) if r["fc_media"] else "—"} for r in ultimas]
rapidas_r  = [{"id":r["id"],"pos":i+1,"fecha":r["fecha"],"nombre":r["nombre"],
               "dist":round(r["distancia_km"],2),"ritmo":fmt_pace(r["ritmo_min_km"])} for i,r in enumerate(top_rapidas)]
largas_r   = [{"id":r["id"],"pos":i+1,"fecha":r["fecha"],"nombre":r["nombre"],
               "dist":round(r["distancia_km"],2),"ritmo":fmt_pace(r["ritmo_min_km"]),
               "desnivel":int(r["desnivel_m"] or 0)} for i,r in enumerate(top_largas)]
maratones_r = [{"id":r["id"],"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
                "ritmo":fmt_pace(r["ritmo_min_km"]),"tiempo":fmt_time(r["distancia_km"],r["ritmo_min_km"])} for r in maratones]
medias_r    = [{"id":r["id"],"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
                "ritmo":fmt_pace(r["ritmo_min_km"]),"tiempo":fmt_time(r["distancia_km"],r["ritmo_min_km"])} for r in medias]
paises_json = json.dumps(sorted(paises_con_carreras))

tiene_fc   = len(fc_anual) > 0
tiene_ef   = len(eficiencia) > 0

años_disponibles = [r["año"] for r in por_año]

all_runs_json = json.dumps([{
    "id":           r["id"],
    "fecha":        r["fecha"],
    "nombre":       (r["nombre"] or "")[:60],
    "distancia_km": round(r["distancia_km"], 4),
    "tiempo_min":   round(r["tiempo_min"], 2) if r["tiempo_min"] else None,
    "ritmo_min_km": round(r["ritmo_min_km"], 4) if r["ritmo_min_km"] else None,
    "velocidad_kmh":round(r["velocidad_kmh"], 2) if r["velocidad_kmh"] else None,
    "desnivel_m":   r["desnivel_m"] or 0,
    "fc_media":     r["fc_media"],
    "fc_max":       r["fc_max"],
    "calorias":     r["calorias"],
    "ciudad":       r["ciudad"] or "",
    "polyline":     r["polyline"] or "",
    "start_lat":    decode_polyline_first(r["polyline"])[0],
    "start_lng":    decode_polyline_first(r["polyline"])[1],
} for r in all_runs_raw])

# ── HTML ──────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Dashboard Carreras · Emi</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/css/jsvectormap.min.css">
<script src="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/js/jsvectormap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/maps/world.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {{
  --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a;
  --accent:#f97316; --accent2:#3b82f6; --accent3:#22c55e; --accent4:#a855f7;
  --text:#e2e8f0; --muted:#94a3b8; --border:#2e3347; --radius:12px;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;padding:24px}}
h1{{font-size:1.8rem;font-weight:700}}
h2{{font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:14px}}
.section-title{{
  font-size:1rem;font-weight:700;color:var(--text);
  margin:32px 0 16px;padding-left:10px;
  border-left:3px solid var(--accent);
}}
.header{{display:flex;align-items:center;gap:16px;margin-bottom:28px;border-bottom:1px solid var(--border);padding-bottom:20px;flex-wrap:wrap}}
.header .logo{{font-size:2.2rem}}
.header .sub{{color:var(--muted);font-size:.9rem;margin-top:2px}}
.sync-btn{{
  margin-left:auto;display:inline-flex;align-items:center;gap:8px;
  background:var(--surface2);border:1px solid var(--border);
  color:var(--text);border-radius:10px;padding:9px 18px;
  font-size:.85rem;font-weight:600;cursor:pointer;transition:all .2s;
  font-family:inherit;
}}
.sync-btn:hover:not(:disabled){{border-color:var(--accent);color:var(--accent)}}
.sync-btn:disabled{{opacity:.6;cursor:not-allowed}}
.sync-btn.syncing{{border-color:var(--accent2);color:var(--accent2)}}
.sync-btn.done{{border-color:var(--accent3);color:var(--accent3)}}
.sync-btn.error{{border-color:#ef4444;color:#ef4444}}
.sync-status{{font-size:.75rem;color:var(--muted);margin-top:4px;text-align:right}}

/* KPI grid */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-bottom:24px}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 16px}}
.kpi .label{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:7px}}
.kpi .value{{font-size:1.65rem;font-weight:700;line-height:1}}
.kpi .unit{{font-size:.78rem;color:var(--muted);margin-top:4px}}
.kpi .trend{{font-size:.75rem;margin-top:5px;font-weight:600}}
.kpi.accent  .value{{color:var(--accent)}}
.kpi.accent2 .value{{color:var(--accent2)}}
.kpi.accent3 .value{{color:var(--accent3)}}
.kpi.accent4 .value{{color:var(--accent4)}}

/* Forma actual */
.forma-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}}
.forma-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 16px}}
.forma-card .label{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
.forma-card .value{{font-size:1.5rem;font-weight:700}}
.forma-card .compare{{font-size:.78rem;color:var(--muted);margin-top:6px}}
.forma-card .compare span{{font-weight:700}}

/* PRs */
.pr-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}}
.pr-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 16px;position:relative;overflow:hidden}}
.pr-card::before{{content:'';position:absolute;top:0;left:0;width:3px;height:100%;background:var(--accent)}}
.pr-card .dist-label{{font-size:.8rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}}
.pr-card .tiempo{{font-size:1.4rem;font-weight:700;color:var(--accent);font-family:monospace;letter-spacing:-.5px}}
.pr-card .ritmo{{font-size:.9rem;color:var(--accent2);font-family:monospace;margin-top:2px}}
.pr-card .meta{{font-size:.75rem;color:var(--muted);margin-top:8px;line-height:1.5}}

/* Mapa */
#world-map{{width:100%;height:420px;background:var(--surface);border-radius:var(--radius)}}
.jvm-tooltip{{background:var(--surface2)!important;border:1px solid var(--border)!important;color:var(--text)!important;font-family:'Segoe UI',system-ui,sans-serif!important;font-size:.82rem!important}}

/* Charts */
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:22px}}
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:22px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px}}
.card.full{{grid-column:1/-1}}
.chart-wrap{{position:relative;height:250px}}
.chart-wrap-sm{{position:relative;height:180px}}

/* Tables */
table{{width:100%;border-collapse:collapse;font-size:.87rem}}
thead th{{text-align:left;padding:9px 12px;color:var(--muted);font-weight:600;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}}
tbody tr{{border-bottom:1px solid var(--border);transition:background .15s}}
tbody tr:hover{{background:var(--surface2)}}
tbody td{{padding:9px 12px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.75rem;font-weight:600}}
.badge-orange{{background:#f9731622;color:var(--accent)}}
.badge-blue{{background:#3b82f622;color:var(--accent2)}}
.badge-green{{background:#22c55e22;color:var(--accent3)}}
.pace{{font-family:monospace;font-size:.93rem;color:var(--accent);font-weight:700}}
.pos{{color:var(--muted);font-weight:700}}

@media(max-width:1000px){{.grid-2,.grid-3,.forma-grid,.pr-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:600px){{.grid-2,.grid-3,.forma-grid,.pr-grid{{grid-template-columns:1fr}}}}

/* ── Filtros ── */
.filter-bar{{
  display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:12px 20px;
  margin-bottom:24px;position:sticky;top:8px;z-index:200;
  box-shadow:0 4px 20px #0007;
}}
.filter-group{{display:flex;align-items:center;gap:8px}}
.filter-group label{{font-size:.75rem;color:var(--muted);font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}}
.filter-group select{{
  background:var(--surface2);border:1px solid var(--border);
  color:var(--text);border-radius:8px;padding:6px 32px 6px 12px;
  font-size:.88rem;cursor:pointer;outline:none;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='%2394a3b8'%3E%3Cpath d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center;
  transition:border-color .15s;
}}
.filter-group select:hover,.filter-group select:focus{{border-color:var(--accent)}}
.filter-reset{{
  background:none;border:1px solid var(--border);color:var(--muted);
  border-radius:8px;padding:5px 12px;font-size:.8rem;cursor:pointer;
  transition:all .15s;
}}
.filter-reset:hover{{border-color:var(--accent);color:var(--accent)}}
.filter-info{{margin-left:auto;font-size:.82rem;color:var(--muted);white-space:nowrap}}
#filterCount{{color:var(--accent);font-weight:700;font-size:1rem}}
.dynamic-label{{color:var(--accent2);font-size:.72rem;font-weight:600;
  text-transform:uppercase;letter-spacing:.05em;margin-left:4px;opacity:.8}}
tr.clickable{{cursor:pointer;transition:background .12s}}
tr.clickable:hover{{background:var(--surface2)!important;outline:1px solid var(--accent);outline-offset:-1px}}

/* ── Modal mapa de país ── */
.country-modal-overlay{{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);
  z-index:400;align-items:center;justify-content:center;padding:16px;
  backdrop-filter:blur(4px);
}}
.country-modal-overlay.open{{display:flex}}
.country-modal-card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:18px;width:100%;max-width:1040px;
  height:82vh;display:flex;flex-direction:column;overflow:hidden;
  box-shadow:0 24px 60px #000c;animation:modalIn .2s ease;
}}
.country-modal-header{{
  display:flex;align-items:center;justify-content:space-between;
  padding:14px 20px;border-bottom:1px solid var(--border);flex-shrink:0;
  background:var(--surface2);
}}
.country-modal-title{{font-size:1.05rem;font-weight:700}}
#countryMap{{flex:1;width:100%}}
/* tooltip Leaflet oscuro */
.leaflet-tooltip{{
  background:var(--surface2)!important;border:1px solid var(--border)!important;
  color:var(--text)!important;border-radius:8px!important;
  font-family:'Segoe UI',system-ui,sans-serif!important;font-size:.8rem!important;
  box-shadow:0 4px 14px #0008!important;padding:6px 10px!important;
}}
.leaflet-tooltip::before{{border-top-color:var(--border)!important}}
/* cursor pointer en países con carreras */
.jvm-region.jvm-element{{cursor:default}}

/* ── Mapa de ruta ── */
.run-map-wrap{{height:260px;border-radius:10px;overflow:hidden;margin-bottom:18px;border:1px solid var(--border);display:none}}
.run-map-wrap.visible{{display:block}}
#runMap{{height:100%;width:100%}}
/* override Leaflet UI para tema oscuro */
.leaflet-control-zoom a{{background:var(--surface2)!important;color:var(--text)!important;border-color:var(--border)!important}}
.leaflet-control-attribution{{background:rgba(15,17,23,.7)!important;color:var(--muted)!important;font-size:.6rem!important}}
.leaflet-control-attribution a{{color:var(--muted)!important}}

/* ── Modal ── */
.modal-overlay{{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
  z-index:500;align-items:center;justify-content:center;padding:20px;
  backdrop-filter:blur(4px);
}}
.modal-overlay.open{{display:flex}}
.modal-card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:18px;max-width:640px;width:100%;
  max-height:90vh;overflow-y:auto;padding:0;position:relative;
  box-shadow:0 24px 60px #000a;animation:modalIn .2s ease;
}}
@keyframes modalIn{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
.modal-header{{
  background:linear-gradient(135deg,var(--surface2),var(--surface));
  padding:24px 28px 20px;border-bottom:1px solid var(--border);
  border-radius:18px 18px 0 0;
}}
.modal-title{{font-size:1.15rem;font-weight:700;line-height:1.3;margin-bottom:4px}}
.modal-sub{{font-size:.82rem;color:var(--muted)}}
.modal-close{{
  position:absolute;top:14px;right:16px;
  background:var(--surface2);border:1px solid var(--border);
  color:var(--muted);border-radius:50%;width:30px;height:30px;
  font-size:.9rem;cursor:pointer;display:flex;align-items:center;
  justify-content:center;transition:all .15s;
}}
.modal-close:hover{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.modal-body{{padding:24px 28px}}
.modal-kpi-grid{{
  display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;
}}
.modal-kpi{{
  background:var(--bg);border:1px solid var(--border);
  border-radius:10px;padding:14px 12px;text-align:center;
}}
.modal-kpi .mk-label{{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}}
.modal-kpi .mk-val{{font-size:1.2rem;font-weight:700;line-height:1}}
.modal-kpi .mk-unit{{font-size:.68rem;color:var(--muted);margin-top:3px}}
.modal-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}}
.modal-stat{{
  background:var(--bg);border:1px solid var(--border);
  border-radius:10px;padding:12px 14px;
  display:flex;align-items:center;justify-content:space-between;
}}
.modal-stat .ms-key{{font-size:.78rem;color:var(--muted)}}
.modal-stat .ms-val{{font-size:.92rem;font-weight:700}}
.perf-bar-wrap{{margin-top:16px}}
.perf-bar-label{{font-size:.75rem;color:var(--muted);margin-bottom:6px}}
.perf-bar-track{{background:var(--surface2);border-radius:99px;height:8px;overflow:hidden;position:relative}}
.perf-bar-fill{{height:100%;border-radius:99px;transition:width .4s ease}}
.perf-bar-ticks{{display:flex;justify-content:space-between;margin-top:3px;font-size:.65rem;color:var(--muted)}}
.modal-link{{
  display:inline-flex;align-items:center;gap:6px;
  margin-top:16px;font-size:.8rem;color:var(--accent2);
  text-decoration:none;border:1px solid var(--border);
  border-radius:8px;padding:6px 14px;transition:all .15s;
}}
.modal-link:hover{{border-color:var(--accent2);background:var(--accent2)11}}
@media(max-width:600px){{.modal-kpi-grid{{grid-template-columns:repeat(2,1fr)}}.modal-row{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="header">
  <div class="logo">🏃</div>
  <div>
    <h1>Dashboard Carreras · Emi</h1>
    <div class="sub">Datos desde 2016 · {stats['total_carreras']} actividades · Actualizado {date.today().strftime('%d/%m/%Y')}</div>
  </div>
  <div style="margin-left:auto;text-align:right">
    <button id="syncBtn" class="sync-btn" onclick="triggerSync()">🔄 Sincronizar</button>
    <div class="sync-status" id="syncStatus"></div>
  </div>
</div>

<!-- ═══ FILTROS ═══ -->
<div class="filter-bar">
  <div class="filter-group">
    <label>📅 Año</label>
    <select id="filterYear" onchange="onFilterChange()">
      <option value="all">Todos los años</option>
      {"".join(f'<option value="{y}">{y}</option>' for y in años_disponibles)}
    </select>
  </div>
  <div class="filter-group">
    <label>🗓 Mes</label>
    <select id="filterMonth" onchange="onFilterChange()">
      <option value="all">Todos los meses</option>
      <option value="01">Enero</option>
      <option value="02">Febrero</option>
      <option value="03">Marzo</option>
      <option value="04">Abril</option>
      <option value="05">Mayo</option>
      <option value="06">Junio</option>
      <option value="07">Julio</option>
      <option value="08">Agosto</option>
      <option value="09">Septiembre</option>
      <option value="10">Octubre</option>
      <option value="11">Noviembre</option>
      <option value="12">Diciembre</option>
    </select>
  </div>
  <button class="filter-reset" onclick="resetFilters()">✕ Reset</button>
  <div class="filter-info">
    Mostrando <span id="filterCount">{stats['total_carreras']}</span> carreras
    <span id="filterDesc"></span>
  </div>
</div>

<!-- ═══ KPIs GLOBALES ═══ -->
<div class="section-title">Resumen global</div>
<div class="kpi-grid">
  <div class="kpi accent">
    <div class="label">Km totales</div>
    <div class="value">{stats['km_totales']:,.0f}</div>
    <div class="unit">kilómetros</div>
  </div>
  <div class="kpi">
    <div class="label">Carreras</div>
    <div class="value">{stats['total_carreras']}</div>
    <div class="unit">actividades</div>
  </div>
  <div class="kpi accent2">
    <div class="label">Ritmo medio</div>
    <div class="value">{fmt_pace(stats['ritmo_medio'])}</div>
    <div class="unit">min/km</div>
  </div>
  <div class="kpi accent3">
    <div class="label">Mejor ritmo</div>
    <div class="value">{fmt_pace(stats['mejor_ritmo'])}</div>
    <div class="unit">min/km (histórico)</div>
  </div>
  <div class="kpi">
    <div class="label">Dist. media</div>
    <div class="value">{stats['distancia_media']}</div>
    <div class="unit">km por carrera</div>
  </div>
  <div class="kpi">
    <div class="label">Más larga</div>
    <div class="value">{stats['max_distancia']}</div>
    <div class="unit">km</div>
  </div>
  <div class="kpi">
    <div class="label">Desnivel total</div>
    <div class="value">{int(stats['desnivel_total']):,}</div>
    <div class="unit">metros D+</div>
  </div>
  <div class="kpi accent4">
    <div class="label">Racha activa</div>
    <div class="value">{racha}</div>
    <div class="unit">semanas consecutivas</div>
  </div>
  <div class="kpi accent3">
    <div class="label">Km/semana</div>
    <div class="value">{km_sem_media}</div>
    <div class="unit">media últimas 4 sem</div>
  </div>
</div>

<!-- ═══ FORMA ACTUAL ═══ -->
<div class="section-title">Forma actual — últimas 4 semanas vs anteriores 4</div>
<div class="forma-grid">
  <div class="forma-card">
    <div class="label">Km totales</div>
    <div class="value" style="color:var(--accent)">{forma_act['km'] or 0} km</div>
    <div class="compare">Antes: {forma_prev['km'] or 0} km &nbsp;<span style="color:{tkm_color}">{tkm_txt}</span></div>
  </div>
  <div class="forma-card">
    <div class="label">Ritmo medio</div>
    <div class="value" style="color:var(--accent2)">{fmt_pace(forma_act['ritmo'])}</div>
    <div class="compare">Antes: {fmt_pace(forma_prev['ritmo'])} &nbsp;<span style="color:{trt_color}">{trt_txt}</span></div>
  </div>
  <div class="forma-card">
    <div class="label">Carreras</div>
    <div class="value" style="color:var(--accent3)">{forma_act['n']}</div>
    <div class="compare">Antes: {forma_prev['n']} &nbsp;
      <span style="color:{'#22c55e' if (forma_act['n'] or 0) >= (forma_prev['n'] or 0) else '#f97316'}">
        {'↑' if (forma_act['n'] or 0) >= (forma_prev['n'] or 0) else '↓'} {abs((forma_act['n'] or 0)-(forma_prev['n'] or 0))}
      </span>
    </div>
  </div>
  <div class="forma-card">
    <div class="label">Este mes vs año anterior</div>
    <div class="value" style="color:var(--accent4)">{mes_act['km'] or 0} km</div>
    <div class="compare">{date.today().strftime('%b')} {date.today().year-1}: {mes_prev_año['km'] or 0} km &nbsp;<span style="color:{mes_km_color}">{mes_km_diff}</span></div>
  </div>
</div>

<!-- ═══ RECORDS PERSONALES ═══ -->
<div class="section-title">Records personales</div>
<div class="pr-grid">
  {"".join(f'''
  <div class="pr-card">
    <div class="dist-label">{r["dist"]}</div>
    <div class="tiempo">{r["tiempo"]}</div>
    <div class="ritmo">{r["ritmo"]} min/km</div>
    <div class="meta">
      📅 {r["fecha"]}<br>
      ⏳ {r["hace"]}<br>
      📍 {r["nombre"]}
    </div>
  </div>''' for r in prs)}
</div>

<!-- ═══ CARGA DE ENTRENAMIENTO ═══ -->
<div class="section-title" id="titleCarga">Carga de entrenamiento — últimas 12 semanas</div>
<div class="grid-2">
  <div class="card">
    <h2>Km por semana <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartSemKm"></canvas></div>
  </div>
  <div class="card">
    <h2>Carreras por semana <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartSemCarr"></canvas></div>
  </div>
</div>

<!-- ═══ EVOLUCION ANUAL ═══ -->
<div class="section-title">Evolución anual</div>
<div class="grid-2">
  <div class="card">
    <h2>Km por año</h2>
    <div class="chart-wrap"><canvas id="chartKmAnual"></canvas></div>
  </div>
  <div class="card">
    <h2>Ritmo medio por año</h2>
    <div class="chart-wrap"><canvas id="chartRitmoAnual"></canvas></div>
  </div>
</div>
<div class="grid-2">
  <div class="card">
    <h2>Número de carreras por año</h2>
    <div class="chart-wrap"><canvas id="chartCarrAnual"></canvas></div>
  </div>
  <div class="card">
    <h2>Distribución por distancia <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartFranjas"></canvas></div>
  </div>
</div>

<!-- ═══ EVOLUCION MENSUAL ═══ -->
<div class="section-title" id="titleMensual">Evolución mensual — últimos 24 meses</div>
<div class="grid-2">
  <div class="card">
    <h2>Km mensuales <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartKmMes"></canvas></div>
  </div>
  <div class="card">
    <h2>Ritmo mensual <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartRitmoMes"></canvas></div>
  </div>
</div>

<!-- ═══ CONSISTENCIA ═══ -->
<div class="section-title" id="titleConsistencia">Consistencia — últimos 13 meses</div>
<div class="grid-2">
  <div class="card">
    <h2>Semanas activas por mes <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartConsistencia"></canvas></div>
  </div>
  <div class="card">
    <h2>Km por mes <span class="dynamic-label">⟳ dinámico</span></h2>
    <div class="chart-wrap"><canvas id="chartConKm"></canvas></div>
  </div>
</div>

<!-- ═══ FC Y EFICIENCIA ═══ -->
{"''''" if not tiene_fc else ""}
<div class="section-title">Frecuencia cardiaca y eficiencia aeróbica</div>
<div class="grid-2">
  <div class="card">
    <h2>FC media por año</h2>
    <div class="chart-wrap"><canvas id="chartFC"></canvas></div>
  </div>
  <div class="card">
    <h2>Eficiencia aeróbica mensual<br><small style="font-size:.7rem;color:var(--muted)">(velocidad m/min ÷ FC × 100 — mayor es mejor)</small></h2>
    <div class="chart-wrap"><canvas id="chartEF"></canvas></div>
  </div>
</div>
{"''''" if not tiene_fc else ""}

<!-- ═══ MAPA DEL MUNDO ═══ -->
<div class="section-title">Países donde he corrido</div>
<div class="card" style="margin-bottom:22px">
  <h2>{len(paises_con_carreras)} {'país' if len(paises_con_carreras)==1 else 'países'} — {', '.join(sorted(paises_con_carreras))}</h2>
  <div id="world-map"></div>
</div>

<!-- ═══ RECORDS Y TABLAS ═══ -->
<div class="section-title">Records y actividades destacadas</div>
<div class="grid-2" style="margin-bottom:18px">
  <div class="card">
    <h2>Top 5 ritmos más rápidos (≥ 5 km)</h2>
    <table>
      <thead><tr><th>#</th><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>Nombre</th></tr></thead>
      <tbody>
        {"".join(f'<tr class="clickable" data-run-id="{r["id"]}" onclick="openRunModal({r["id"]})"><td class="pos">{r["pos"]}</td><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in rapidas_r)}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Top 5 carreras más largas</h2>
    <table>
      <thead><tr><th>#</th><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>D+</th></tr></thead>
      <tbody>
        {"".join(f'<tr class="clickable" data-run-id="{r["id"]}" onclick="openRunModal({r["id"]})"><td class="pos">{r["pos"]}</td><td>{r["fecha"]}</td><td><strong>{r["dist"]} km</strong></td><td class="pace">{r["ritmo"]}</td><td style="color:var(--accent3)">{r["desnivel"]}m</td></tr>' for r in largas_r)}
      </tbody>
    </table>
  </div>
</div>

<div class="grid-2" style="margin-bottom:18px">
  <div class="card">
    <h2>Maratones — ordenadas por ritmo</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>Tiempo</th><th>Nombre</th></tr></thead>
      <tbody>
        {"".join(f'<tr class="clickable" data-run-id="{r["id"]}" onclick="openRunModal({r["id"]})"><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td><span class="badge badge-orange">{r["tiempo"]}</span></td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in maratones_r)}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Medias maratones — ordenadas por ritmo</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>Tiempo</th><th>Nombre</th></tr></thead>
      <tbody>
        {"".join(f'<tr class="clickable" data-run-id="{r["id"]}" onclick="openRunModal({r["id"]})"><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td><span class="badge badge-blue">{r["tiempo"]}</span></td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in medias_r)}
      </tbody>
    </table>
  </div>
</div>

<div class="card">
  <h2>Últimas 10 carreras <span class="dynamic-label">⟳ dinámico</span></h2>
  <table>
    <thead><tr><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>D+</th><th>FC</th><th>Nombre</th></tr></thead>
    <tbody id="ultimasBody">
      {"".join(f'<tr class="clickable" data-run-id="{r["id"]}" onclick="openRunModal({r["id"]})"><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td style="color:var(--accent3)">{r["desnivel"]}m</td><td style="color:var(--accent2)">{r["fc"]}</td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:45]}</td></tr>' for r in ultimas_r)}
    </tbody>
  </table>
</div>

<!-- ═══ MODAL MAPA DE PAÍS ═══ -->
<div id="countryModalOverlay" class="country-modal-overlay" onclick="if(event.target===this)closeCountryModal()">
  <div class="country-modal-card">
    <div class="country-modal-header">
      <div class="country-modal-title" id="countryModalTitle">—</div>
      <div style="display:flex;align-items:center;gap:12px">
        <span id="countryRunInfo" style="font-size:.8rem;color:var(--muted)"></span>
        <button class="modal-close" style="position:static" onclick="closeCountryModal()">✕</button>
      </div>
    </div>
    <div id="countryMap"></div>
  </div>
</div>

<!-- ═══ MODAL DETALLE CARRERA ═══ -->
<div id="modalOverlay" class="modal-overlay" onclick="if(event.target===this)closeRunModal()">
  <div class="modal-card">
    <button class="modal-close" onclick="closeRunModal()">✕</button>
    <div class="modal-header">
      <div class="modal-title" id="modalTitle">—</div>
      <div class="modal-sub" id="modalSub">—</div>
    </div>
    <div class="run-map-wrap" id="runMapWrap">
      <div id="runMap"></div>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<script>
const AÑOS=    {json.dumps(años_l)};
const KM_AÑO=  {json.dumps(años_km)};
const RT_AÑO=  {json.dumps(años_ritmo)};
const RL_AÑO=  {json.dumps(años_rl)};
const CARR_AÑO={json.dumps(años_carr)};

const MES_L=   {json.dumps(mes_l)};
const MES_KM=  {json.dumps(mes_km)};
const MES_RT=  {json.dumps(mes_ritmo)};
const MES_RL=  {json.dumps(mes_rl)};

const SEM_L=   {json.dumps(sem_l)};
const SEM_KM=  {json.dumps(sem_km)};
const SEM_CARR={json.dumps(sem_carr)};

const FC_L=    {json.dumps(fc_l)};
const FC_V=    {json.dumps(fc_v)};
const EF_L=    {json.dumps(ef_l)};
const EF_V=    {json.dumps(ef_v)};

const CONS_L=  {json.dumps(cons_l)};
const CONS_SEM={json.dumps(cons_sem)};
const CONS_KM= {json.dumps(cons_km)};

const FL=      {json.dumps(fl)};
const FC_CNT=  {json.dumps(fc_counts)};

const TIENE_FC = {'true' if tiene_fc else 'false'};

// Todas las carreras para filtros dinámicos
const ALL_RUNS = {all_runs_json};

const O='#f97316', B='#3b82f6', G='#22c55e', P='#a855f7', T='#14b8a6', R='#ec4899';
const BORDER='#2e3347', MUTED='#94a3b8';
const g = {{color:BORDER, drawBorder:false}};

Chart.defaults.color = MUTED;
Chart.defaults.borderColor = BORDER;
Chart.defaults.font.family = "'Segoe UI',system-ui,sans-serif";

const paceAxis = {{
  grid: g, reverse: true,
  ticks: {{ callback: v => {{ const m=Math.floor(v),s=Math.round((v-m)*60); return m+':'+(s<10?'0':'')+s; }} }}
}};
const paceTip = labels => ({{
  callbacks: {{ label: ctx => ' '+labels[ctx.dataIndex]+' min/km' }}
}});

// Km semanales
let chartSemKm = new Chart('chartSemKm', {{type:'bar', data:{{labels:SEM_L, datasets:[{{
  label:'Km', data:SEM_KM, backgroundColor:O+'99', borderColor:O, borderWidth:2, borderRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Carreras semanales
let chartSemCarr = new Chart('chartSemCarr', {{type:'bar', data:{{labels:SEM_L, datasets:[{{
  label:'Carreras', data:SEM_CARR, backgroundColor:T+'99', borderColor:T, borderWidth:2, borderRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{stepSize:1}}}}}}
}}}});

// Km anual (estático)
new Chart('chartKmAnual', {{type:'bar', data:{{labels:AÑOS, datasets:[{{
  label:'Km', data:KM_AÑO, backgroundColor:O+'99', borderColor:O, borderWidth:2, borderRadius:6
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Ritmo anual (estático)
new Chart('chartRitmoAnual', {{type:'line', data:{{labels:AÑOS, datasets:[{{
  label:'Ritmo', data:RT_AÑO, borderColor:B, backgroundColor:B+'22',
  fill:true, tension:0.4, pointBackgroundColor:B, pointRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}, tooltip:paceTip(RL_AÑO)}},
  scales:{{x:{{grid:g}}, y:paceAxis}}
}}}});

// Carreras anual (estático)
new Chart('chartCarrAnual', {{type:'bar', data:{{labels:AÑOS, datasets:[{{
  label:'Carreras', data:CARR_AÑO, backgroundColor:P+'88', borderColor:P, borderWidth:2, borderRadius:6
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g}}, y:{{grid:g}}}}
}}}});

// Donut franjas
let chartFranjas = new Chart('chartFranjas', {{type:'doughnut', data:{{labels:FL, datasets:[{{
  data:FC_CNT,
  backgroundColor:[O+'99',B+'99',G+'99',P+'99',R+'99',T+'99'],
  borderColor:[O,B,G,P,R,T], borderWidth:2
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{position:'right', labels:{{boxWidth:12,font:{{size:11}}}}}},
    tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{ctx.raw}} carreras`}}}}
  }}
}}}});

// Km mensual
let chartKmMes = new Chart('chartKmMes', {{type:'bar', data:{{labels:MES_L, datasets:[{{
  label:'Km', data:MES_KM, backgroundColor:G+'88', borderColor:G, borderWidth:1, borderRadius:4
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Ritmo mensual
let chartRitmoMes = new Chart('chartRitmoMes', {{type:'line', data:{{labels:MES_L, datasets:[{{
  label:'Ritmo', data:MES_RT, borderColor:P, backgroundColor:P+'22',
  fill:true, tension:0.4, pointRadius:3, pointBackgroundColor:P
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}, tooltip:paceTip(MES_RL)}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:paceAxis}}
}}}});

// Consistencia - semanas activas
let chartConsistencia = new Chart('chartConsistencia', {{type:'bar', data:{{labels:CONS_L, datasets:[{{
  label:'Semanas activas', data:CONS_SEM, backgroundColor:T+'88', borderColor:T, borderWidth:1, borderRadius:4
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, max:5, ticks:{{stepSize:1}}}}}}
}}}});

// Consistencia - km por mes
let chartConKm = new Chart('chartConKm', {{type:'bar', data:{{labels:CONS_L, datasets:[{{
  label:'Km', data:CONS_KM, backgroundColor:R+'88', borderColor:R, borderWidth:1, borderRadius:4
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Mapa del mundo
const PAISES = {paises_json};
try {{
  new jsVectorMap({{
    selector: '#world-map',
    map: 'world',
    backgroundColor: '#1a1d27',
    zoomOnScroll: false,
    zoomButtons: false,
    regionStyle: {{
      initial:  {{ fill: '#2e3347', stroke: '#0f1117', strokeWidth: 0.5 }},
      hover:    {{ fill: '#f9731688', cursor: 'pointer' }},
      selected: {{ fill: '#f97316' }},
    }},
    selectedRegions: PAISES,
    onRegionTooltipShow(e, tooltip, code) {{
      if (PAISES.includes(code)) tooltip.text(tooltip.text() + ' ✅ — clic para ver carreras');
    }},
    onRegionClick(event, code) {{
      if (PAISES.includes(code)) openCountryMap(code);
    }},
  }});
}} catch(e) {{ console.warn('Mapa no disponible:', e); }}

// ══════════════════════════════════════════════════════════════
// MAPA DE PAÍS — dots por carrera
// ══════════════════════════════════════════════════════════════
const COUNTRY_NAMES = {{
  ES:'España', AU:'Australia', GB:'Reino Unido', PT:'Portugal',
  DE:'Alemania', FR:'Francia', IT:'Italia', US:'EE.UU.', JP:'Japón', CH:'Suiza'
}};

// Bounding boxes [SW, NE]
const COUNTRY_BOUNDS = {{
  ES:[[ 35.9, -9.3 ],[43.8, 4.3 ]],
  AU:[[-43.7,113.3 ],[-10.7,153.6]],
  GB:[[ 49.9, -8.2 ],[60.9, 1.8 ]],
  PT:[[ 36.9, -9.5 ],[42.2,-6.2 ]],
  DE:[[ 47.3,  5.9 ],[55.1,15.0 ]],
  FR:[[ 41.3, -5.1 ],[51.1, 9.6 ]],
  IT:[[ 36.6,  6.6 ],[47.1,18.5 ]],
  US:[[ 24.5,-125.0],[49.4,-66.9]],
  JP:[[ 24.2, 122.9],[45.5,145.8]],
  CH:[[ 45.8,  5.9 ],[47.8,10.5 ]],
}};

function getRunsInCountry(iso) {{
  const b = COUNTRY_BOUNDS[iso];
  if (!b) return [];
  return ALL_RUNS.filter(r => {{
    if (r.start_lat == null) return false;
    return r.start_lat >= b[0][0] && r.start_lat <= b[1][0]
        && r.start_lng >= b[0][1] && r.start_lng <= b[1][1];
  }});
}}

// Función de color por ritmo relativo a la media del grupo
function paceColor(ritmo, avg) {{
  if (!ritmo || !avg) return '#f97316';
  const diff = ritmo - avg;           // positivo = más lento
  if (diff < -0.3) return '#22c55e';  // verde: rápido
  if (diff >  0.3) return '#ef4444';  // rojo: lento
  return '#f97316';                    // naranja: normal
}}

let _countryMap = null;

function openCountryMap(iso) {{
  const name  = COUNTRY_NAMES[iso] || iso;
  const runs  = getRunsInCountry(iso);
  const total = runs.length;

  // Calcular km totales y ritmo medio para el header
  const kmTot = runs.reduce((s,r) => s + (r.distancia_km||0), 0);
  const ritmos = runs.filter(r => r.ritmo_min_km).map(r => r.ritmo_min_km);
  const avgRt  = ritmos.length ? ritmos.reduce((a,b)=>a+b,0)/ritmos.length : null;

  document.getElementById('countryModalTitle').innerHTML =
    `🗺️ ${{name}}`;
  document.getElementById('countryRunInfo').textContent =
    `${{total}} carrera${{total!==1?'s':''}}  ·  ${{kmTot.toFixed(0)}} km` +
    (avgRt ? `  ·  ritmo medio ${{fmtPaceJS(avgRt)}}` : '');

  document.getElementById('countryModalOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';

  if (_countryMap) {{ _countryMap.remove(); _countryMap = null; }}

  setTimeout(() => {{
    _countryMap = L.map('countryMap', {{ zoomControl:true, attributionControl:true }});

    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution:'© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>',
      subdomains:'abcd', maxZoom:19
    }}).addTo(_countryMap);

    // Ajustar vista al país
    const bb = COUNTRY_BOUNDS[iso];
    if (bb) _countryMap.fitBounds([bb[0], bb[1]], {{padding:[20,20]}});

    // Añadir una bolita por carrera
    runs.forEach(r => {{
      const color = paceColor(r.ritmo_min_km, avgRt);
      const marker = L.circleMarker([r.start_lat, r.start_lng], {{
        radius: 6, color: '#fff', weight: 1.2,
        fillColor: color, fillOpacity: 0.85,
      }}).addTo(_countryMap);

      const tip = `<strong>${{r.nombre}}</strong><br>
        📅 ${{r.fecha}}&nbsp;&nbsp;
        📏 ${{r.distancia_km.toFixed(1)}} km&nbsp;&nbsp;
        ⏱ ${{fmtPaceJS(r.ritmo_min_km)}} min/km` +
        (r.fc_media ? `<br>❤️ ${{Math.round(r.fc_media)}} ppm` : '');

      marker.bindTooltip(tip, {{direction:'top', offset:[0,-4]}});
      marker.on('click', () => openRunModal(r.id));
      // Cursor pointer
      marker.getElement && marker.on('add', () => {{
        if (marker.getElement()) marker.getElement().style.cursor = 'pointer';
      }});
    }});

    // Leyenda de colores
    const legend = L.control({{position:'bottomright'}});
    legend.onAdd = () => {{
      const d = L.DomUtil.create('div');
      d.style.cssText = 'background:rgba(26,29,39,.9);border:1px solid #2e3347;border-radius:8px;padding:8px 12px;font-size:.75rem;color:#e2e8f0;line-height:1.8';
      d.innerHTML = '<div style="font-weight:700;margin-bottom:4px">Ritmo vs media</div>'
        + '<span style="color:#22c55e">●</span> Rápido&nbsp;&nbsp;'
        + '<span style="color:#f97316">●</span> Normal&nbsp;&nbsp;'
        + '<span style="color:#ef4444">●</span> Lento';
      return d;
    }};
    legend.addTo(_countryMap);

  }}, 80);
}}

function closeCountryModal() {{
  document.getElementById('countryModalOverlay').classList.remove('open');
  document.body.style.overflow = '';
  if (_countryMap) {{ _countryMap.remove(); _countryMap = null; }}
}}

// FC y Eficiencia (solo si hay datos, estáticos)
if(TIENE_FC && document.getElementById('chartFC')){{
  new Chart('chartFC', {{type:'line', data:{{labels:FC_L, datasets:[{{
    label:'FC media', data:FC_V, borderColor:R, backgroundColor:R+'22',
    fill:true, tension:0.4, pointBackgroundColor:R, pointRadius:5
  }}]}}, options:{{responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{x:{{grid:g}}, y:{{grid:g, ticks:{{callback:v=>v+' ppm'}}}}}}
  }}}});
  new Chart('chartEF', {{type:'line', data:{{labels:EF_L, datasets:[{{
    label:'Eficiencia', data:EF_V, borderColor:T, backgroundColor:T+'22',
    fill:true, tension:0.4, pointRadius:3, pointBackgroundColor:T
  }}]}}, options:{{responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g}}}}
  }}}});
}}

// ══════════════════════════════════════════════════════════════
// FILTROS DINÁMICOS
// ══════════════════════════════════════════════════════════════
const MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];

function fmtPaceJS(p) {{
  if (!p) return '--:--';
  const m = Math.floor(p), s = Math.round((p - m) * 60);
  return m + ':' + (s < 10 ? '0' : '') + s;
}}

function getISOWeekStr(date) {{
  const d = new Date(date);
  const day = d.getDay() || 7;
  d.setDate(d.getDate() + 4 - day);
  const y = d.getFullYear();
  const start = new Date(y, 0, 1);
  const w = Math.ceil((((d - start) / 86400000) + 1) / 7);
  return y + '-' + String(w).padStart(2, '0');
}}

function avg(arr) {{
  const a = arr.filter(v => v != null);
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
}}

function updateDynamicCharts() {{
  const yr = document.getElementById('filterYear').value;
  const mo = document.getElementById('filterMonth').value;
  const isFiltered = yr !== 'all' || mo !== 'all';

  // ── Filtrar carreras ──────────────────────────────────────
  let runs = ALL_RUNS;
  if (yr !== 'all') runs = runs.filter(r => r.fecha.startsWith(yr));
  if (mo !== 'all') runs = runs.filter(r => r.fecha.substring(5, 7) === mo);

  // ── Contador ─────────────────────────────────────────────
  document.getElementById('filterCount').textContent = runs.length;
  const descEl = document.getElementById('filterDesc');
  if (!isFiltered) {{
    descEl.textContent = '';
  }} else {{
    const parts = [];
    if (yr !== 'all') parts.push(yr);
    if (mo !== 'all') parts.push(MONTH_NAMES[parseInt(mo) - 1]);
    descEl.textContent = ' · ' + parts.join(' ');
  }}

  // ── Agrupar por mes ────────────────────────────────────────
  const byMonth = {{}};
  runs.forEach(r => {{
    const mk = r.fecha.substring(0, 7);
    if (!byMonth[mk]) byMonth[mk] = {{ km: 0, ritmos: [], n: 0 }};
    byMonth[mk].km     += r.distancia_km;
    byMonth[mk].n      += 1;
    if (r.ritmo_min_km) byMonth[mk].ritmos.push(r.ritmo_min_km);
  }});
  const mesKeys = Object.keys(byMonth).sort();
  const newMesKm  = mesKeys.map(k => Math.round(byMonth[k].km * 10) / 10);
  const newMesRt  = mesKeys.map(k => {{
    const a = avg(byMonth[k].ritmos);
    return a ? Math.round(a * 10000) / 10000 : null;
  }});
  const newMesRl  = newMesRt.map(fmtPaceJS);

  chartKmMes.data.labels = mesKeys;
  chartKmMes.data.datasets[0].data = newMesKm;
  chartKmMes.update('none');

  chartRitmoMes.data.labels = mesKeys;
  chartRitmoMes.data.datasets[0].data = newMesRt;
  chartRitmoMes.options.plugins.tooltip = {{ callbacks: {{ label: ctx => ' ' + newMesRl[ctx.dataIndex] + ' min/km' }} }};
  chartRitmoMes.update('none');

  // ── Actualizar títulos de sección ─────────────────────────
  const sfx = isFiltered ? ' — ' + (yr !== 'all' ? yr : '') + (mo !== 'all' ? (yr !== 'all' ? ' · ' : '') + MONTH_NAMES[parseInt(mo)-1] : '') : '';
  document.getElementById('titleMensual').textContent       = 'Evolución mensual' + (isFiltered ? sfx : ' — últimos 24 meses');
  document.getElementById('titleConsistencia').textContent  = 'Consistencia'      + (isFiltered ? sfx : ' — últimos 13 meses');
  document.getElementById('titleCarga').textContent         = 'Carga de entrenamiento' + (isFiltered ? sfx : ' — últimas 12 semanas');

  // ── Agrupar por semana ────────────────────────────────────
  const byWeek = {{}};
  runs.forEach(r => {{
    const wk = getISOWeekStr(r.fecha);
    if (!byWeek[wk]) byWeek[wk] = {{ km: 0, n: 0 }};
    byWeek[wk].km += r.distancia_km;
    byWeek[wk].n  += 1;
  }});
  let wkKeys = Object.keys(byWeek).sort();
  if (!isFiltered) wkKeys = wkKeys.slice(-12);  // defecto: últimas 12

  chartSemKm.data.labels = wkKeys;
  chartSemKm.data.datasets[0].data = wkKeys.map(k => Math.round(byWeek[k].km * 10) / 10);
  chartSemKm.update('none');

  chartSemCarr.data.labels = wkKeys;
  chartSemCarr.data.datasets[0].data = wkKeys.map(k => byWeek[k].n);
  chartSemCarr.update('none');

  // ── Consistencia (semanas activas por mes) ────────────────
  const byCons = {{}};
  runs.forEach(r => {{
    const mk = r.fecha.substring(0, 7);
    if (!byCons[mk]) byCons[mk] = {{ semanas: new Set(), km: 0 }};
    byCons[mk].semanas.add(getISOWeekStr(r.fecha));
    byCons[mk].km += r.distancia_km;
  }});
  let consKeys = Object.keys(byCons).sort();
  if (!isFiltered) consKeys = consKeys.slice(-13);  // defecto: últimos 13

  chartConsistencia.data.labels = consKeys;
  chartConsistencia.data.datasets[0].data = consKeys.map(k => byCons[k] ? byCons[k].semanas.size : 0);
  chartConsistencia.options.scales.y.max = isFiltered ? undefined : 5;
  chartConsistencia.update('none');

  chartConKm.data.labels = consKeys;
  chartConKm.data.datasets[0].data = consKeys.map(k => byCons[k] ? Math.round(byCons[k].km * 10) / 10 : 0);
  chartConKm.update('none');

  // ── Franjas de distancia ──────────────────────────────────
  const franjaFns = [
    d => d < 5,
    d => d >= 5  && d < 8,
    d => d >= 8  && d < 12,
    d => d >= 12 && d < 17,
    d => d >= 17 && d < 22,
    d => d >= 22,
  ];
  chartFranjas.data.datasets[0].data = franjaFns.map(fn => runs.filter(r => fn(r.distancia_km)).length);
  chartFranjas.update('none');

  // ── Tabla últimas 10 carreras ─────────────────────────────
  const last10 = runs.slice().reverse().slice(0, 10);
  document.getElementById('ultimasBody').innerHTML = last10.map(r => `
    <tr class="clickable" data-run-id="${{r.id}}" onclick="openRunModal(${{r.id}})">
      <td>${{r.fecha}}</td>
      <td>${{r.distancia_km.toFixed(2)}} km</td>
      <td class="pace">${{fmtPaceJS(r.ritmo_min_km)}}</td>
      <td style="color:var(--accent3)">${{Math.round(r.desnivel_m || 0)}}m</td>
      <td style="color:var(--accent2)">${{r.fc_media ? Math.round(r.fc_media) : '—'}}</td>
      <td style="color:var(--muted);font-size:.8rem">${{r.nombre.substring(0, 45)}}</td>
    </tr>`).join('');
}}

function onFilterChange() {{
  const yr = document.getElementById('filterYear').value;
  const mo = document.getElementById('filterMonth').value;
  // Si seleccionan mes sin año, habilitar mes es OK (filtra por ese mes de todos los años)
  updateDynamicCharts();
}}

function resetFilters() {{
  document.getElementById('filterYear').value  = 'all';
  document.getElementById('filterMonth').value = 'all';
  updateDynamicCharts();
}}

// ══════════════════════════════════════════════════════════════
// MODAL DETALLE CARRERA
// ══════════════════════════════════════════════════════════════
const RUN_MAP = {{}};
ALL_RUNS.forEach(r => {{ RUN_MAP[r.id] = r; }});

// ── Decodificador de Google Encoded Polyline ──────────────────
function decodePolyline(str) {{
  const coords = [];
  let idx = 0, lat = 0, lng = 0;
  while (idx < str.length) {{
    let b, shift = 0, result = 0;
    do {{ b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; }} while (b >= 0x20);
    lat += (result & 1) ? ~(result >> 1) : (result >> 1);
    shift = 0; result = 0;
    do {{ b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; }} while (b >= 0x20);
    lng += (result & 1) ? ~(result >> 1) : (result >> 1);
    coords.push([lat / 1e5, lng / 1e5]);
  }}
  return coords;
}}

// ── Mapa Leaflet del recorrido ────────────────────────────────
let _leafletMap = null;

function showRunMap(polyline) {{
  const wrap = document.getElementById('runMapWrap');
  if (!polyline) {{ wrap.classList.remove('visible'); return; }}

  const coords = decodePolyline(polyline);
  if (coords.length < 2) {{ wrap.classList.remove('visible'); return; }}

  wrap.classList.add('visible');

  // Destruir instancia anterior
  if (_leafletMap) {{ _leafletMap.remove(); _leafletMap = null; }}

  // Pequeño delay para que el DOM esté visible antes de init
  setTimeout(() => {{
    _leafletMap = L.map('runMap', {{ zoomControl:true, attributionControl:true }});

    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution:'© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>',
      subdomains:'abcd', maxZoom:19
    }}).addTo(_leafletMap);

    // Traza naranja
    const track = L.polyline(coords, {{ color:'#f97316', weight:4, opacity:.9, lineJoin:'round' }}).addTo(_leafletMap);
    _leafletMap.fitBounds(track.getBounds(), {{ padding:[18,18] }});

    // Marcador inicio (verde) y fin (rojo)
    const dot = (latlng, color) => L.circleMarker(latlng, {{
      radius:7, color:'#fff', weight:2,
      fillColor:color, fillOpacity:1
    }}).addTo(_leafletMap);

    dot(coords[0], '#22c55e').bindTooltip('Inicio');
    dot(coords[coords.length - 1], '#ef4444').bindTooltip('Fin');
  }}, 80);
}}

// Calcula cuantil de ritmo: qué % de carreras similares son más lentas
function pacePercentile(run) {{
  const d = run.distancia_km;
  const margin = d * 0.15;
  const similar = ALL_RUNS.filter(r => r.ritmo_min_km && Math.abs(r.distancia_km - d) <= margin);
  if (similar.length < 3) return null;
  const slower = similar.filter(r => r.ritmo_min_km > run.ritmo_min_km).length;
  return Math.round(slower / similar.length * 100);
}}

function fmtTotalTime(tmin) {{
  if (!tmin) return '--';
  const h = Math.floor(tmin / 60);
  const m = Math.floor(tmin % 60);
  const s = Math.round((tmin - Math.floor(tmin)) * 60);
  if (h > 0) return h + 'h ' + String(m).padStart(2,'0') + 'm ' + String(s).padStart(2,'0') + 's';
  return m + 'm ' + String(s).padStart(2,'0') + 's';
}}

function openRunModal(id) {{
  const r = RUN_MAP[id];
  if (!r) return;

  // Estadísticas de referencia (carreras de distancia similar ±15%)
  const margin = r.distancia_km * 0.15;
  const similar = ALL_RUNS.filter(x => x.ritmo_min_km && Math.abs(x.distancia_km - r.distancia_km) <= margin);
  const avgRitmo = similar.length ? similar.reduce((a,x) => a + x.ritmo_min_km, 0) / similar.length : null;
  const bestRitmo = similar.length ? Math.min(...similar.map(x => x.ritmo_min_km)) : null;
  const worstRitmo = similar.length ? Math.max(...similar.map(x => x.ritmo_min_km)) : null;
  const pctil = pacePercentile(r);

  // Año de la carrera: ritmo medio de ese año
  const yr = r.fecha.substring(0, 4);
  const yrRuns = ALL_RUNS.filter(x => x.fecha.startsWith(yr) && x.ritmo_min_km);
  const yrAvgRitmo = yrRuns.length ? yrRuns.reduce((a,x) => a + x.ritmo_min_km, 0) / yrRuns.length : null;

  // Header
  const ciudad = r.ciudad ? ' · 📍 ' + r.ciudad : '';
  document.getElementById('modalTitle').textContent = r.nombre || 'Carrera sin nombre';
  document.getElementById('modalSub').textContent   = '📅 ' + r.fecha + ciudad + '  ·  🆔 ' + r.id;

  // KPIs principales
  const kpis = [
    {{ label:'Distancia', val: r.distancia_km.toFixed(2), unit:'km', color:'var(--accent)' }},
    {{ label:'Tiempo',    val: fmtTotalTime(r.tiempo_min), unit:'total', color:'var(--accent2)' }},
    {{ label:'Ritmo',     val: fmtPaceJS(r.ritmo_min_km), unit:'min/km', color:'var(--accent3)' }},
    {{ label:'Velocidad', val: r.velocidad_kmh ? r.velocidad_kmh.toFixed(1) : '—', unit:'km/h', color:'var(--accent4)' }},
  ];

  const kpiHtml = kpis.map(k => `
    <div class="modal-kpi">
      <div class="mk-label">${{k.label}}</div>
      <div class="mk-val" style="color:${{k.color}}">${{k.val}}</div>
      <div class="mk-unit">${{k.unit}}</div>
    </div>`).join('');

  // Stats secundarios
  const stats2 = [
    {{ k:'FC media',   v: r.fc_media  ? Math.round(r.fc_media)  + ' ppm' : '—', c:'var(--accent)'  }},
    {{ k:'FC máxima',  v: r.fc_max    ? Math.round(r.fc_max)    + ' ppm' : '—', c:'#ef4444'        }},
    {{ k:'Calorías',   v: r.calorias  ? Math.round(r.calorias)  + ' kcal': '—', c:'var(--accent3)' }},
    {{ k:'Desnivel',   v: r.desnivel_m ? Math.round(r.desnivel_m) + ' m D+': '0 m', c:'var(--accent2)' }},
  ];
  const stats2Html = stats2.map(s => `
    <div class="modal-stat">
      <span class="ms-key">${{s.k}}</span>
      <span class="ms-val" style="color:${{s.c}}">${{s.v}}</span>
    </div>`).join('');

  // Barra de rendimiento (ritmo vs mejor/peor en distancias similares)
  let perfHtml = '';
  if (r.ritmo_min_km && bestRitmo && worstRitmo && similar.length >= 5) {{
    const range  = worstRitmo - bestRitmo;
    const pos    = range > 0 ? (r.ritmo_min_km - bestRitmo) / range : 0.5;
    const fillPct = Math.round((1 - pos) * 100);  // 100% = mejor ritmo
    const barColor = fillPct >= 70 ? 'var(--accent3)' : fillPct >= 40 ? 'var(--accent)' : '#ef4444';
    perfHtml = `
      <div class="perf-bar-wrap">
        <div class="perf-bar-label">
          Rendimiento en carreras de distancia similar (±15%)
          ${{pctil !== null ? `— mejor que el <strong style="color:var(--accent)">${{pctil}}%</strong> de tus ${{similar.length}} carreras similares` : ''}}
        </div>
        <div class="perf-bar-track">
          <div class="perf-bar-fill" style="width:${{fillPct}}%;background:${{barColor}}"></div>
        </div>
        <div class="perf-bar-ticks">
          <span>🏆 Mejor: ${{fmtPaceJS(bestRitmo)}}</span>
          ${{avgRitmo ? `<span>⌀ Media: ${{fmtPaceJS(avgRitmo)}}</span>` : ''}}
          <span>🐢 Peor: ${{fmtPaceJS(worstRitmo)}}</span>
        </div>
      </div>`;
  }}

  // Comparación con media anual
  let yrHtml = '';
  if (r.ritmo_min_km && yrAvgRitmo) {{
    const diff = yrAvgRitmo - r.ritmo_min_km;  // positivo = más rápido que media
    const diffFmt = (diff > 0 ? '▲ ' : '▼ ') + fmtPaceJS(Math.abs(diff));
    const diffColor = diff > 0 ? 'var(--accent3)' : '#ef4444';
    yrHtml = `
      <div class="modal-stat" style="margin-top:8px;grid-column:1/-1">
        <span class="ms-key">vs media de ${{yr}} (todas distancias)</span>
        <span class="ms-val" style="color:${{diffColor}}">${{diffFmt}} min/km</span>
      </div>`;
  }}

  // Link a Strava
  const stravaHtml = `<a class="modal-link" href="https://www.strava.com/activities/${{r.id}}" target="_blank" rel="noopener">
    Ver en Strava ↗
  </a>`;

  document.getElementById('modalBody').innerHTML = `
    <div class="modal-kpi-grid">${{kpiHtml}}</div>
    <div class="modal-row">${{stats2Html}}${{yrHtml}}</div>
    ${{perfHtml}}
    ${{stravaHtml}}
  `;

  // Mostrar el mapa (si hay polyline)
  showRunMap(r.polyline || '');

  document.getElementById('modalOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}}

function closeRunModal() {{
  document.getElementById('modalOverlay').classList.remove('open');
  document.body.style.overflow = '';
  // Destruir el mapa al cerrar para liberar memoria
  if (_leafletMap) {{ _leafletMap.remove(); _leafletMap = null; }}
  document.getElementById('runMapWrap').classList.remove('visible');
}}

// ══════════════════════════════════════════════════════════════
// BOTÓN SYNC MANUAL — GitHub Actions workflow_dispatch
// Token guardado en localStorage (nunca en el HTML)
// ══════════════════════════════════════════════════════════════
const GH_REPO     = 'Emiliofgarcia/carreras-dashboard';
const GH_WORKFLOW = 'sync.yml';

function sleep(ms) {{ return new Promise(r => setTimeout(r, ms)); }}

function getToken() {{
  let t = localStorage.getItem('gh_sync_token');
  if (!t) {{
    t = prompt('Introduce tu GitHub Personal Access Token (Actions:write):\n(Se guardará en tu navegador, no en el código)');
    if (!t) return null;
    localStorage.setItem('gh_sync_token', t.trim());
  }}
  return t.trim();
}}

async function triggerSync() {{
  const GH_TOKEN = getToken();
  if (!GH_TOKEN) return;
  const btn = document.getElementById('syncBtn');
  const status = document.getElementById('syncStatus');
  btn.disabled = true;
  btn.className = 'sync-btn syncing';
  btn.innerHTML = '⏳ Lanzando...';
  status.textContent = '';

  // 1. Disparar workflow
  const t0 = Date.now();
  const dispatch = await fetch(
    `https://api.github.com/repos/${{GH_REPO}}/actions/workflows/${{GH_WORKFLOW}}/dispatches`,
    {{
      method: 'POST',
      headers: {{
        'Authorization': `Bearer ${{GH_TOKEN}}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      }},
      body: JSON.stringify({{ ref: 'main' }})
    }}
  );

  if (dispatch.status !== 204) {{
    btn.className = 'sync-btn error'; btn.innerHTML = '❌ Error al lanzar';
    status.textContent = `HTTP ${{dispatch.status}}`;
    btn.disabled = false; return;
  }}

  // 2. Esperar a que aparezca el run (máx 30s)
  btn.innerHTML = '⏳ Iniciando...';
  let runId = null;
  for (let i = 0; i < 10 && !runId; i++) {{
    await sleep(3000);
    const r = await fetch(
      `https://api.github.com/repos/${{GH_REPO}}/actions/workflows/${{GH_WORKFLOW}}/runs?per_page=1`,
      {{ headers: {{ 'Authorization': `Bearer ${{GH_TOKEN}}`, 'Accept': 'application/vnd.github.v3+json' }} }}
    );
    const data = await r.json();
    const run = data.workflow_runs?.[0];
    if (run && new Date(run.created_at).getTime() >= t0 - 5000) runId = run.id;
  }}

  if (!runId) {{
    btn.className = 'sync-btn error'; btn.innerHTML = '❌ Timeout';
    btn.disabled = false; return;
  }}

  // 3. Esperar a que termine (máx 5 min)
  btn.innerHTML = '⏳ Sincronizando...';
  status.textContent = 'Tarda ~1 minuto';
  for (let i = 0; i < 30; i++) {{
    await sleep(10000);
    const r = await fetch(
      `https://api.github.com/repos/${{GH_REPO}}/actions/runs/${{runId}}`,
      {{ headers: {{ 'Authorization': `Bearer ${{GH_TOKEN}}`, 'Accept': 'application/vnd.github.v3+json' }} }}
    );
    const run = await r.json();
    const elapsed = Math.round((Date.now() - t0) / 1000);
    status.textContent = `${{run.status}} · ${{elapsed}}s`;
    if (run.status === 'completed') {{
      if (run.conclusion === 'success') {{
        btn.className = 'sync-btn done'; btn.innerHTML = '✅ Listo — recargando...';
        status.textContent = `Completado en ${{elapsed}}s`;
        await sleep(2000); location.reload();
      }} else {{
        btn.className = 'sync-btn error'; btn.innerHTML = `❌ ${{run.conclusion}}`;
        btn.disabled = false;
      }}
      return;
    }}
  }}
  btn.className = 'sync-btn error'; btn.innerHTML = '❌ Timeout';
  btn.disabled = false;
}}

// Cerrar con Escape (prioridad: modal de detalle → modal de país)
document.addEventListener('keydown', e => {{
  if (e.key !== 'Escape') return;
  if (document.getElementById('modalOverlay').classList.contains('open')) {{
    closeRunModal();
  }} else if (document.getElementById('countryModalOverlay').classList.contains('open')) {{
    closeCountryModal();
  }}
}});
</script>
</body>
</html>"""

_base        = os.path.dirname(os.path.abspath(__file__))
output_path  = os.path.join(_base, "dashboard.html")
index_path   = os.path.join(_base, "index.html")

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)
with open(index_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Dashboard generado: {index_path}")

# ── Auto-publicar en GitHub Pages (solo fuera de CI) ─────────
import subprocess, os
# En GitHub Actions el workflow hace el commit/push — aquí no tocamos git
if os.environ.get("GITHUB_ACTIONS"):
    print("CI detectado — git push omitido (lo hace el workflow)")
else:
    repo = r"D:\BackUp Emi\Code\StravaApi"
    try:
        subprocess.run(["git", "-C", repo, "add", "index.html"], check=True)
        result = subprocess.run(["git", "-C", repo, "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            from datetime import datetime as _dt
            msg = f"Dashboard actualizado {_dt.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "-C", repo, "commit", "-m", msg], check=True)
            subprocess.run(["git", "-C", repo, "push", "origin", "main"], check=True)
            print("Publicado en GitHub Pages correctamente")
        else:
            print("GitHub Pages: sin cambios, no se publica")
    except Exception as e:
        print(f"Aviso: no se pudo publicar en GitHub Pages: {e}")

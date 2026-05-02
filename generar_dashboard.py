import sqlite3
import json
import config
from datetime import date, timedelta

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
    SELECT fecha, nombre, distancia_km, ritmo_min_km, desnivel_m, fc_media
    FROM carreras ORDER BY fecha DESC LIMIT 10
""").fetchall()

top_rapidas = conn.execute("""
    SELECT fecha, nombre, distancia_km, ritmo_min_km
    FROM carreras WHERE distancia_km >= 5
    ORDER BY ritmo_min_km ASC LIMIT 5
""").fetchall()

top_largas = conn.execute("""
    SELECT fecha, nombre, distancia_km, ritmo_min_km, desnivel_m
    FROM carreras ORDER BY distancia_km DESC LIMIT 5
""").fetchall()

maratones = conn.execute("""
    SELECT fecha, nombre, distancia_km, ritmo_min_km
    FROM carreras WHERE distancia_km >= 40
    ORDER BY ritmo_min_km ASC
""").fetchall()

medias = conn.execute("""
    SELECT fecha, nombre, distancia_km, ritmo_min_km
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

ultimas_r  = [{"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
               "ritmo":fmt_pace(r["ritmo_min_km"]),"desnivel":int(r["desnivel_m"] or 0),
               "fc": int(r["fc_media"]) if r["fc_media"] else "—"} for r in ultimas]
rapidas_r  = [{"pos":i+1,"fecha":r["fecha"],"nombre":r["nombre"],
               "dist":round(r["distancia_km"],2),"ritmo":fmt_pace(r["ritmo_min_km"])} for i,r in enumerate(top_rapidas)]
largas_r   = [{"pos":i+1,"fecha":r["fecha"],"nombre":r["nombre"],
               "dist":round(r["distancia_km"],2),"ritmo":fmt_pace(r["ritmo_min_km"]),
               "desnivel":int(r["desnivel_m"] or 0)} for i,r in enumerate(top_largas)]
maratones_r = [{"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
                "ritmo":fmt_pace(r["ritmo_min_km"]),"tiempo":fmt_time(r["distancia_km"],r["ritmo_min_km"])} for r in maratones]
medias_r    = [{"fecha":r["fecha"],"nombre":r["nombre"],"dist":round(r["distancia_km"],2),
                "ritmo":fmt_pace(r["ritmo_min_km"]),"tiempo":fmt_time(r["distancia_km"],r["ritmo_min_km"])} for r in medias]
paises_json = json.dumps(sorted(paises_con_carreras))

tiene_fc   = len(fc_anual) > 0
tiene_ef   = len(eficiencia) > 0

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
.header{{display:flex;align-items:center;gap:16px;margin-bottom:28px;border-bottom:1px solid var(--border);padding-bottom:20px}}
.header .logo{{font-size:2.2rem}}
.header .sub{{color:var(--muted);font-size:.9rem;margin-top:2px}}

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
</style>
</head>
<body>

<div class="header">
  <div class="logo">🏃</div>
  <div>
    <h1>Dashboard Carreras · Emi</h1>
    <div class="sub">Datos desde 2016 · {stats['total_carreras']} actividades · Actualizado {date.today().strftime('%d/%m/%Y')}</div>
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
<div class="section-title">Carga de entrenamiento — últimas 12 semanas</div>
<div class="grid-2">
  <div class="card">
    <h2>Km por semana</h2>
    <div class="chart-wrap"><canvas id="chartSemKm"></canvas></div>
  </div>
  <div class="card">
    <h2>Carreras por semana</h2>
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
    <h2>Distribución por distancia</h2>
    <div class="chart-wrap"><canvas id="chartFranjas"></canvas></div>
  </div>
</div>

<!-- ═══ EVOLUCION MENSUAL ═══ -->
<div class="section-title">Evolución mensual — últimos 24 meses</div>
<div class="grid-2">
  <div class="card">
    <h2>Km mensuales</h2>
    <div class="chart-wrap"><canvas id="chartKmMes"></canvas></div>
  </div>
  <div class="card">
    <h2>Ritmo mensual</h2>
    <div class="chart-wrap"><canvas id="chartRitmoMes"></canvas></div>
  </div>
</div>

<!-- ═══ CONSISTENCIA ═══ -->
<div class="section-title">Consistencia — últimos 13 meses</div>
<div class="grid-2">
  <div class="card">
    <h2>Semanas activas por mes</h2>
    <div class="chart-wrap"><canvas id="chartConsistencia"></canvas></div>
  </div>
  <div class="card">
    <h2>Km por mes</h2>
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
        {"".join(f'<tr><td class="pos">{r["pos"]}</td><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in rapidas_r)}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Top 5 carreras más largas</h2>
    <table>
      <thead><tr><th>#</th><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>D+</th></tr></thead>
      <tbody>
        {"".join(f'<tr><td class="pos">{r["pos"]}</td><td>{r["fecha"]}</td><td><strong>{r["dist"]} km</strong></td><td class="pace">{r["ritmo"]}</td><td style="color:var(--accent3)">{r["desnivel"]}m</td></tr>' for r in largas_r)}
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
        {"".join(f'<tr><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td><span class="badge badge-orange">{r["tiempo"]}</span></td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in maratones_r)}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Medias maratones — ordenadas por ritmo</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>Tiempo</th><th>Nombre</th></tr></thead>
      <tbody>
        {"".join(f'<tr><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td><span class="badge badge-blue">{r["tiempo"]}</span></td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:35]}</td></tr>' for r in medias_r)}
      </tbody>
    </table>
  </div>
</div>

<div class="card">
  <h2>Últimas 10 carreras</h2>
  <table>
    <thead><tr><th>Fecha</th><th>Dist</th><th>Ritmo</th><th>D+</th><th>FC</th><th>Nombre</th></tr></thead>
    <tbody>
      {"".join(f'<tr><td>{r["fecha"]}</td><td>{r["dist"]} km</td><td class="pace">{r["ritmo"]}</td><td style="color:var(--accent3)">{r["desnivel"]}m</td><td style="color:var(--accent2)">{r["fc"]}</td><td style="color:var(--muted);font-size:.8rem">{r["nombre"][:45]}</td></tr>' for r in ultimas_r)}
    </tbody>
  </table>
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
new Chart('chartSemKm', {{type:'bar', data:{{labels:SEM_L, datasets:[{{
  label:'Km', data:SEM_KM, backgroundColor:O+'99', borderColor:O, borderWidth:2, borderRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Carreras semanales
new Chart('chartSemCarr', {{type:'bar', data:{{labels:SEM_L, datasets:[{{
  label:'Carreras', data:SEM_CARR, backgroundColor:T+'99', borderColor:T, borderWidth:2, borderRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{stepSize:1}}}}}}
}}}});

// Km anual
new Chart('chartKmAnual', {{type:'bar', data:{{labels:AÑOS, datasets:[{{
  label:'Km', data:KM_AÑO, backgroundColor:O+'99', borderColor:O, borderWidth:2, borderRadius:6
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Ritmo anual
new Chart('chartRitmoAnual', {{type:'line', data:{{labels:AÑOS, datasets:[{{
  label:'Ritmo', data:RT_AÑO, borderColor:B, backgroundColor:B+'22',
  fill:true, tension:0.4, pointBackgroundColor:B, pointRadius:5
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}, tooltip:paceTip(RL_AÑO)}},
  scales:{{x:{{grid:g}}, y:paceAxis}}
}}}});

// Carreras anual
new Chart('chartCarrAnual', {{type:'bar', data:{{labels:AÑOS, datasets:[{{
  label:'Carreras', data:CARR_AÑO, backgroundColor:P+'88', borderColor:P, borderWidth:2, borderRadius:6
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g}}, y:{{grid:g}}}}
}}}});

// Donut franjas
new Chart('chartFranjas', {{type:'doughnut', data:{{labels:FL, datasets:[{{
  data:FC_CNT,
  backgroundColor:[O+'99',B+'99',G+'99',P+'99',R+'99',T+'99'],
  borderColor:[O,B,G,P,R,T], borderWidth:2
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{position:'right', labels:{{boxWidth:12,font:{{size:11}}}}}},
    tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{ctx.raw}} carreras`}}}}
  }}
}}}});

// Km mensual
new Chart('chartKmMes', {{type:'bar', data:{{labels:MES_L, datasets:[{{
  label:'Km', data:MES_KM, backgroundColor:G+'88', borderColor:G, borderWidth:1, borderRadius:4
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, ticks:{{callback:v=>v+' km'}}}}}}
}}}});

// Ritmo mensual
new Chart('chartRitmoMes', {{type:'line', data:{{labels:MES_L, datasets:[{{
  label:'Ritmo', data:MES_RT, borderColor:P, backgroundColor:P+'22',
  fill:true, tension:0.4, pointRadius:3, pointBackgroundColor:P
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}, tooltip:paceTip(MES_RL)}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:paceAxis}}
}}}});

// Consistencia - semanas activas
new Chart('chartConsistencia', {{type:'bar', data:{{labels:CONS_L, datasets:[{{
  label:'Semanas activas', data:CONS_SEM, backgroundColor:T+'88', borderColor:T, borderWidth:1, borderRadius:4
}}]}}, options:{{responsive:true, maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:g, ticks:{{maxRotation:45,font:{{size:10}}}}}}, y:{{grid:g, max:5, ticks:{{stepSize:1}}}}}}
}}}});

// Consistencia - km por mes
new Chart('chartConKm', {{type:'bar', data:{{labels:CONS_L, datasets:[{{
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
      if (PAISES.includes(code)) tooltip.text(tooltip.text() + ' ✅');
    }},
  }});
}} catch(e) {{ console.warn('Mapa no disponible:', e); }}

// FC y Eficiencia (solo si hay datos)
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
</script>
</body>
</html>"""

output_path = r"D:\BackUp Emi\Code\StravaApi\dashboard.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Dashboard generado: {output_path}")

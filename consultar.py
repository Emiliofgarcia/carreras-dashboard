import sqlite3
import sys
import config

sys.stdout.reconfigure(encoding='utf-8')

def fmt_pace(p):
    if p is None:
        return "--:--"
    m = int(p)
    s = int(round((p - m) * 60))
    return f"{m}:{s:02d}"

def consultar(pregunta=None):
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    # Estadísticas generales
    stats = conn.execute("""
        SELECT
            COUNT(*) as total_carreras,
            ROUND(SUM(distancia_km), 1) as km_totales,
            ROUND(AVG(distancia_km), 2) as distancia_media,
            MIN(ritmo_min_km) as mejor_ritmo,
            AVG(ritmo_min_km) as ritmo_medio,
            ROUND(MAX(distancia_km), 2) as max_distancia,
            ROUND(SUM(desnivel_m), 0) as desnivel_total
        FROM carreras
    """).fetchone()

    # Por año
    por_año = conn.execute("""
        SELECT
            strftime('%Y', fecha) as año,
            COUNT(*) as carreras,
            ROUND(SUM(distancia_km), 1) as km_totales,
            ROUND(AVG(distancia_km), 2) as dist_media,
            AVG(ritmo_min_km) as ritmo_medio
        FROM carreras
        GROUP BY año
        ORDER BY año
    """).fetchall()

    # Últimas 10 carreras
    ultimas = conn.execute("""
        SELECT fecha, nombre, distancia_km, ritmo_min_km
        FROM carreras
        ORDER BY fecha DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    print("\n===== RESUMEN GLOBAL =====")
    print(f"Total carreras:     {stats['total_carreras']}")
    print(f"Km totales:         {stats['km_totales']} km")
    print(f"Distancia media:    {stats['distancia_media']} km")
    print(f"Mejor ritmo:        {fmt_pace(stats['mejor_ritmo'])} min/km")
    print(f"Ritmo medio:        {fmt_pace(stats['ritmo_medio'])} min/km")
    print(f"Carrera mas larga:  {stats['max_distancia']} km")
    print(f"Desnivel total:     {stats['desnivel_total']} m")

    print("\n===== POR ANNO =====")
    print(f"{'Anno':<6} {'Carreras':<10} {'Km totales':<12} {'Dist media':<12} {'Ritmo medio'}")
    for r in por_año:
        print(f"{r['año']:<6} {r['carreras']:<10} {r['km_totales']:<12} {r['dist_media']:<12} {fmt_pace(r['ritmo_medio'])}")

    print("\n===== ÚLTIMAS 10 CARRERAS =====")
    for r in ultimas:
        print(f"{r['fecha']} | {r['distancia_km']:6.2f} km | {fmt_pace(r['ritmo_min_km'])} min/km | {r['nombre']}")

    # Mejores carreras por franja de distancia
    franjas = [
        ("< 5 km",    "distancia_km < 5"),
        ("5 - 8 km",  "distancia_km >= 5  AND distancia_km < 8"),
        ("8 - 12 km", "distancia_km >= 8  AND distancia_km < 12"),
        ("12-17 km",  "distancia_km >= 12 AND distancia_km < 17"),
        ("17-22 km",  "distancia_km >= 17 AND distancia_km < 22"),
        ("> 22 km",   "distancia_km >= 22"),
    ]
    print("\n===== MEJOR RITMO POR FRANJA DE DISTANCIA =====")
    conn2 = sqlite3.connect(config.DB_PATH)
    conn2.row_factory = sqlite3.Row
    for label, cond in franjas:
        row = conn2.execute(f"""
            SELECT fecha, nombre, distancia_km, ritmo_min_km
            FROM carreras
            WHERE {cond}
            ORDER BY ritmo_min_km ASC
            LIMIT 1
        """).fetchone()
        if row:
            print(f"  {label:<10} | {fmt_pace(row['ritmo_min_km'])} min/km | {row['distancia_km']:6.2f} km | {row['fecha']} | {row['nombre'][:40]}")

    # Evolución mensual últimos 24 meses
    evolucion = conn2.execute("""
        SELECT
            strftime('%Y-%m', fecha) as mes,
            COUNT(*) as carreras,
            ROUND(SUM(distancia_km), 1) as km_mes,
            ROUND(AVG(distancia_km), 2) as dist_media,
            AVG(ritmo_min_km) as ritmo_medio
        FROM carreras
        WHERE fecha >= date('now', '-24 months')
        GROUP BY mes
        ORDER BY mes
    """).fetchall()

    print("\n===== EVOLUCIÓN MENSUAL (últimos 24 meses) =====")
    print(f"  {'Mes':<8} {'Carr':>5} {'km mes':>8} {'Media':>7} {'Ritmo':>7}  Barra")
    for r in evolucion:
        bar_len = max(0, int((6.5 - r['ritmo_medio']) * 28))
        bar = "█" * bar_len
        print(f"  {r['mes']}  {r['carreras']:>4}  {r['km_mes']:>7}  {r['dist_media']:>6.1f}km  {fmt_pace(r['ritmo_medio'])}  {bar}")

    # Top 5 carreras más largas
    top_largas = conn2.execute("""
        SELECT fecha, nombre, distancia_km, ritmo_min_km, desnivel_m
        FROM carreras
        ORDER BY distancia_km DESC
        LIMIT 5
    """).fetchall()

    print("\n===== TOP 5 CARRERAS MÁS LARGAS =====")
    for i, r in enumerate(top_largas, 1):
        print(f"  {i}. {r['distancia_km']:6.2f} km | {fmt_pace(r['ritmo_min_km'])} min/km | D+ {r['desnivel_m']:.0f}m | {r['fecha']} | {r['nombre'][:40]}")

    # Top 5 ritmos más rápidos (distancia >= 5 km)
    top_rapidos = conn2.execute("""
        SELECT fecha, nombre, distancia_km, ritmo_min_km
        FROM carreras
        WHERE distancia_km >= 5
        ORDER BY ritmo_min_km ASC
        LIMIT 5
    """).fetchall()

    print("\n===== TOP 5 RITMOS MÁS RÁPIDOS (>=5 km) =====")
    for i, r in enumerate(top_rapidos, 1):
        print(f"  {i}. {fmt_pace(r['ritmo_min_km'])} min/km | {r['distancia_km']:6.2f} km | {r['fecha']} | {r['nombre'][:40]}")

    # Maratones y medias maratones
    grandes = conn2.execute("""
        SELECT fecha, nombre, distancia_km, ritmo_min_km
        FROM carreras
        WHERE distancia_km >= 19
        ORDER BY ritmo_min_km ASC
    """).fetchall()

    if grandes:
        print("\n===== MARATONES Y MEDIAS MARATONES =====")
        print(f"  {'Fecha':<12} {'Distancia':>10} {'Ritmo':>7}  {'Tiempo estimado':<16}  Nombre")
        for r in grandes:
            tiempo = r['distancia_km'] * r['ritmo_min_km']
            h = int(tiempo // 60)
            m = int(tiempo % 60)
            print(f"  {r['fecha']:<12} {r['distancia_km']:>9.2f}km  {fmt_pace(r['ritmo_min_km'])}  {h}h{m:02d}min          {r['nombre'][:35]}")

    conn2.close()

if __name__ == "__main__":
    consultar()

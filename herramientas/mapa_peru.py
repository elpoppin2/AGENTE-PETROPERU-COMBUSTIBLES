"""Genera assets/peru-departamentos.json: contornos de los 25 departamentos del Perú
proyectados a coordenadas SVG, y la ubicación de cada planta.

Los contornos vienen de juaneladio/peru-geojson (Mozilla Public License 2.0):
https://github.com/juaneladio/peru-geojson

Uso: python herramientas/mapa_peru.py
"""
import json
import math
from pathlib import Path

import requests

URL = "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_departamental_simple.geojson"
SALIDA = Path(__file__).resolve().parent.parent / "assets" / "peru-departamentos.json"
ANCHO = 400

NOMBRES = {
    "AMAZONAS": "Amazonas", "ANCASH": "Áncash", "APURIMAC": "Apurímac", "AREQUIPA": "Arequipa",
    "AYACUCHO": "Ayacucho", "CAJAMARCA": "Cajamarca", "CALLAO": "Callao", "CUSCO": "Cusco",
    "HUANCAVELICA": "Huancavelica", "HUANUCO": "Huánuco", "ICA": "Ica", "JUNIN": "Junín",
    "LA LIBERTAD": "La Libertad", "LAMBAYEQUE": "Lambayeque", "LIMA": "Lima", "LORETO": "Loreto",
    "MADRE DE DIOS": "Madre de Dios", "MOQUEGUA": "Moquegua", "PASCO": "Pasco", "PIURA": "Piura",
    "PUNO": "Puno", "SAN MARTIN": "San Martín", "TACNA": "Tacna", "TUMBES": "Tumbes", "UCAYALI": "Ucayali",
}

# Ubicación aproximada (latitud, longitud) de las plantas de Petroperú y de Osinergmin.
PLANTAS = {
    "TALARA": (-4.58, -81.27), "PIURA": (-5.19, -80.63), "ETEN": (-6.91, -79.86),
    "EL MILAGRO": (-5.64, -78.53), "SALAVERRY": (-8.23, -78.98), "CHIMBOTE": (-9.08, -78.59),
    "SUPE": (-10.80, -77.72), "CALLAO": (-12.05, -77.14), "CONCHAN": (-12.26, -76.93),
    "PISCO": (-13.71, -76.20), "MOLLENDO": (-17.02, -72.01), "ILO": (-17.64, -71.34),
    "CUSCO": (-13.53, -71.97), "JULIACA": (-15.50, -70.13), "PTO. MALDONADO": (-12.59, -69.19),
    "TARAPOTO": (-6.49, -76.37), "YURIMAGUAS": (-5.90, -76.12), "IQUITOS": (-3.75, -73.25),
    "PUCALLPA": (-8.38, -74.55), "CERRO DE PASCO": (-10.68, -76.26),
}


def poligonos(geom):
    return geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


def dentro(lon, lat, anillo):
    c = False
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            c = not c
    return c


def main():
    geo = requests.get(URL, timeout=60).json()
    anillos = [r for f in geo["features"] for p in poligonos(f["geometry"]) for r in p]
    lons = [x for r in anillos for x, _ in r]
    lats = [y for r in anillos for _, y in r]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))  # equirectangular corregida
    escala = ANCHO / ((max(lons) - min(lons)) * k)
    alto = round((max(lats) - min(lats)) * escala)
    xy = lambda lon, lat: (round((lon - min(lons)) * k * escala, 1), round((max(lats) - lat) * escala, 1))

    departamentos = []
    for f in sorted(geo["features"], key=lambda f: f["properties"]["NOMBDEP"]):
        clave = f["properties"]["NOMBDEP"]
        d = ""
        for p in poligonos(f["geometry"]):
            for r in p:
                pts = [xy(*c) for c in r]
                d += "M" + "L".join(f"{x:g},{y:g}" for x, y in pts) + "Z"
        departamentos.append({"clave": clave, "nombre": NOMBRES[clave], "d": d})

    plantas = {}
    for planta, (lat, lon) in PLANTAS.items():
        dep = next((f["properties"]["NOMBDEP"] for f in geo["features"]
                    for p in poligonos(f["geometry"]) if dentro(lon, lat, p[0])), None)
        if dep is None:  # puertos sobre la línea de costa: el departamento más cercano
            dep = min(geo["features"], key=lambda f: min((lon - x) ** 2 + (lat - y) ** 2 for p in poligonos(f["geometry"])
                                                         for x, y in p[0]))["properties"]["NOMBDEP"]
        x, y = xy(lon, lat)
        plantas[planta] = {"x": x, "y": y, "departamento": dep}

    SALIDA.write_text(json.dumps({
        "fuente": "juaneladio/peru-geojson, Mozilla Public License 2.0",
        "ancho": ANCHO, "alto": alto, "departamentos": departamentos, "plantas": plantas,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{SALIDA}: {len(departamentos)} departamentos, {SALIDA.stat().st_size // 1024} KB")
    for p, v in plantas.items():
        print(f"  {p:16} {v['departamento']}")


if __name__ == "__main__":
    main()

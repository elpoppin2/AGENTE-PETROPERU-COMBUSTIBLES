#!/usr/bin/env python3
"""Agente diario de precios del Diésel B5 S-50 y Diésel B5 S-50 UV de Petroperú.

Cada ejecución:
  1. Entra a la página de precios de Petroperú.
  2. Sigue cada enlace de precios (páginas HTML o PDF) y extrae los precios
     del Diésel B5 S-50 y del Diésel B5 S-50 UV (uso vehicular).
  3. Guarda una fila por combustible y ubicación en data/historial.csv.
     Si Petroperú no publicó cambios (o la web no responde), se registra el
     último precio conocido, marcado como "ultimo_registrado".

Uso:
  python agente_petroperu.py              # ejecución normal (una vez al día)
  python agente_petroperu.py --descubrir  # sólo muestra enlaces y precios hallados
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URLS_INICIO = os.environ.get(
    "PETROPERU_URLS",
    "https://www.petroperu.com.pe/productos/precios-de-venta/",
).split(",")
DOMINIOS_PERMITIDOS = ("petroperu.com.pe",)
PALABRAS_ENLACE = ("precio", "lista", "combustible", "tarifa")
MAX_PAGINAS = int(os.environ.get("PETROPERU_MAX_PAGINAS", "40"))
MAX_PROFUNDIDAD = 2
ZONA = ZoneInfo("America/Lima")

DIR_DATOS = Path(os.environ.get("PETROPERU_DATOS", Path(__file__).parent / "data"))
HISTORIAL = DIR_DATOS / "historial.csv"
ACTUALES = DIR_DATOS / "precios_actuales.json"
COLUMNAS = [
    "fecha_consulta", "combustible", "ubicacion", "precio", "estado",
    "fecha_precio", "fuente",
]

# Sólo se registran estos dos diésel. El orden importa: el primer patrón que
# coincide gana, así "B5 S-50 UV" no se confunde con el "B5 S-50" a secas.
# Acepta variantes como "Diésel B5 S-50 UV", "Diesel B5-S50UV", "DB5 S-50"
# y "Diesel B5 S-50 (Uso Vehicular)".
_B5_S50 = r"(?:diesel\s*(?:db)?\s*|\bd)b5\W*s\W*50"
COMBUSTIBLES = [
    ("DIESEL_B5_S50_UV", _B5_S50 + r"\W*(?:uv|.*uso\s*vehicular)"),
    ("DIESEL_B5_S50", _B5_S50),
]
EXCLUIR = re.compile(r"industrial|marino|turbo|residual|aviacion|jet|petroleo\s*industrial|asfalto|solvente")
NUMERO = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,4}))(?![\d.,])")
PRECIO_MIN, PRECIO_MAX = 1.0, 100.0  # soles por galón/kg razonables

log = logging.getLogger("agente_petroperu")


@dataclass
class Precio:
    combustible: str
    ubicacion: str
    precio: float
    fuente: str


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def identificar_combustible(texto: str) -> str | None:
    t = normalizar(texto)
    if not t or EXCLUIR.search(t):
        return None
    for clave, patron in COMBUSTIBLES:
        if re.search(patron, t):
            return clave
    return None


def a_precio(texto: str) -> float | None:
    m = NUMERO.search(texto or "")
    if not m:
        return None
    valor = float(m.group(1).replace(",", "."))
    return valor if PRECIO_MIN <= valor <= PRECIO_MAX else None


def limpiar_ubicacion(texto: str, defecto: str) -> str:
    t = re.sub(r"\s+", " ", texto or "").strip(" :-")
    if not t or a_precio(t) is not None or len(t) > 80:
        return defecto
    return t


# --------------------------------------------------------------------------
# Extracción
# --------------------------------------------------------------------------

def precios_de_tabla(filas: list[list[str]], fuente: str, ubicacion_defecto: str) -> list[Precio]:
    """Admite tablas con combustibles en filas (plantas en columnas) o al revés."""
    filas = [[(c or "").strip() for c in f] for f in filas if any((c or "").strip() for c in f)]
    if not filas:
        return []
    encabezado = filas[0]
    resultado: list[Precio] = []

    combustibles_en_encabezado = [identificar_combustible(c) for c in encabezado]
    if sum(1 for c in combustibles_en_encabezado if c) >= 2:
        # Combustibles como columnas; cada fila es una ubicación/planta.
        for fila in filas[1:]:
            ubicacion = limpiar_ubicacion(fila[0] if fila else "", ubicacion_defecto)
            for i, celda in enumerate(fila):
                clave = combustibles_en_encabezado[i] if i < len(combustibles_en_encabezado) else None
                valor = a_precio(celda)
                if clave and valor is not None:
                    resultado.append(Precio(clave, ubicacion, valor, fuente))
        return resultado

    # Combustibles como filas; cada columna numérica es una ubicación/planta.
    # El nombre del producto puede venir partido en varias celdas
    # ("Diesel B5" | "S-50 UV"), así que se unen las celdas previas al primer precio.
    for fila in filas:
        idx = next((i for i, c in enumerate(fila) if a_precio(c) is not None), len(fila))
        clave = identificar_combustible(" ".join(fila[:idx]))
        if clave is None:
            continue
        for i, celda in enumerate(fila[idx:], start=idx):
            valor = a_precio(celda)
            if valor is None:
                continue
            columna = encabezado[i] if i < len(encabezado) and encabezado is not fila else ""
            resultado.append(Precio(clave, limpiar_ubicacion(columna, ubicacion_defecto), valor, fuente))
    return resultado


def precios_de_texto(texto: str, fuente: str, ubicacion: str) -> list[Precio]:
    """Respaldo: líneas del tipo 'Diesel B5 S-50 UV ..... 14.75'."""
    resultado = []
    for linea in texto.splitlines():
        clave = identificar_combustible(linea)
        if not clave:
            continue
        resto = re.split(r"s\W*50", normalizar(linea), maxsplit=1)[-1]
        valor = a_precio(resto)
        if valor is not None:
            resultado.append(Precio(clave, ubicacion, valor, fuente))
    return resultado


def extraer_html(html: str, fuente: str, ubicacion: str) -> list[Precio]:
    sopa = BeautifulSoup(html, "html.parser")
    precios: list[Precio] = []
    for tabla in sopa.find_all("table"):
        filas = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in tabla.find_all("tr")]
        precios += precios_de_tabla(filas, fuente, ubicacion)
    if not precios:
        precios = precios_de_texto(sopa.get_text("\n"), fuente, ubicacion)
    return precios


def extraer_pdf(contenido: bytes, fuente: str, ubicacion: str) -> list[Precio]:
    import pdfplumber

    precios: list[Precio] = []
    texto_total = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            # Primero tablas con bordes; si no hay, tablas alineadas sólo por texto.
            for ajustes in ({}, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
                hallados = []
                for tabla in pagina.extract_tables(ajustes) or []:
                    hallados += precios_de_tabla(tabla, fuente, ubicacion)
                if hallados:
                    precios += hallados
                    break
            texto_total.append(pagina.extract_text() or "")
    if not precios:
        precios = precios_de_texto("\n".join(texto_total), fuente, ubicacion)
    return precios


# --------------------------------------------------------------------------
# Navegación
# --------------------------------------------------------------------------

def nueva_sesion() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (agente-precios-petroperu; consulta diaria)"
    return s


def descargar(sesion: requests.Session, url: str, intentos: int = 3) -> requests.Response | None:
    for n in range(1, intentos + 1):
        try:
            r = sesion.get(url, timeout=30)
            r.raise_for_status()
            if "charset" not in r.headers.get("Content-Type", "").lower():
                r.encoding = r.apparent_encoding  # evita "ConchÃ¡n" si no declara codificación
            return r
        except requests.RequestException as e:
            log.warning("Intento %d/%d falló para %s: %s", n, intentos, url, e)
            time.sleep(2 ** n)
    return None


def enlace_relevante(url: str, texto: str) -> bool:
    dominio = urlparse(url).netloc.lower()
    if urlparse(url).scheme not in ("http", "https"):
        return False
    if not any(dominio == d or dominio.endswith("." + d) for d in DOMINIOS_PERMITIDOS):
        return False
    t = normalizar(texto + " " + url)
    return any(p in t for p in PALABRAS_ENLACE) or bool(identificar_combustible(texto))


def recorrer(urls_inicio: list[str], sesion: requests.Session) -> tuple[list[Precio], list[str]]:
    """Visita la página de precios y cada enlace de precios que contiene."""
    pendientes = [(u.strip(), 0, "General") for u in urls_inicio if u.strip()]
    visitadas: set[str] = set()
    precios: list[Precio] = []
    paginas_ok: list[str] = []

    while pendientes and len(visitadas) < MAX_PAGINAS:
        url, profundidad, etiqueta = pendientes.pop(0)
        url = url.split("#")[0]
        if url in visitadas:
            continue
        visitadas.add(url)
        r = descargar(sesion, url)
        if r is None:
            continue
        paginas_ok.append(url)
        tipo = r.headers.get("Content-Type", "").lower()

        if "pdf" in tipo or url.lower().endswith(".pdf"):
            try:
                hallados = extraer_pdf(r.content, url, etiqueta)
            except Exception as e:  # PDF dañado o escaneado
                log.warning("No se pudo leer el PDF %s: %s", url, e)
                hallados = []
            log.info("PDF  %s -> %d precios", url, len(hallados))
            precios += hallados
            continue

        html = r.text
        hallados = extraer_html(html, url, etiqueta)
        log.info("HTML %s -> %d precios", url, len(hallados))
        precios += hallados

        if profundidad >= MAX_PROFUNDIDAD:
            continue
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            destino = urljoin(r.url, a["href"]).split("#")[0]
            texto = a.get_text(" ", strip=True) or a.get("title", "")
            if destino not in visitadas and enlace_relevante(destino, texto):
                pendientes.append((destino, profundidad + 1, limpiar_ubicacion(texto, etiqueta)))

    return deduplicar(precios), paginas_ok


def deduplicar(precios: list[Precio]) -> list[Precio]:
    unicos: dict[tuple[str, str], Precio] = {}
    for p in precios:
        unicos.setdefault((p.combustible, p.ubicacion), p)
    return list(unicos.values())


# --------------------------------------------------------------------------
# Historial
# --------------------------------------------------------------------------

def leer_historial() -> list[dict]:
    if not HISTORIAL.exists():
        return []
    with HISTORIAL.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ultimos_precios(historial: list[dict], antes_de: str) -> dict[tuple[str, str], dict]:
    ultimos: dict[tuple[str, str], dict] = {}
    for fila in historial:
        if fila["fecha_consulta"] < antes_de:
            ultimos[(fila["combustible"], fila["ubicacion"])] = fila
    return ultimos


def registrar(precios: list[Precio], hoy: str) -> list[dict]:
    """Combina lo obtenido hoy con el último precio conocido de cada combustible."""
    historial = leer_historial()
    anteriores = ultimos_precios(historial, hoy)
    filas_hoy: dict[tuple[str, str], dict] = {}

    for p in precios:
        previo = anteriores.get((p.combustible, p.ubicacion))
        sin_cambio = previo is not None and abs(float(previo["precio"]) - p.precio) < 1e-6
        filas_hoy[(p.combustible, p.ubicacion)] = {
            "fecha_consulta": hoy,
            "combustible": p.combustible,
            "ubicacion": p.ubicacion,
            "precio": f"{p.precio:.2f}",
            "estado": "sin_cambio" if sin_cambio else "actualizado",
            "fecha_precio": previo["fecha_precio"] if sin_cambio else hoy,
            "fuente": p.fuente,
        }

    # Lo que no se pudo obtener hoy se completa con el último precio registrado.
    for clave, previo in anteriores.items():
        if clave not in filas_hoy:
            filas_hoy[clave] = {**previo, "fecha_consulta": hoy, "estado": "ultimo_registrado"}

    # Si el agente corre dos veces el mismo día, la última corrida reemplaza a la anterior.
    nuevo = [f for f in historial if f["fecha_consulta"] != hoy] + sorted(
        filas_hoy.values(), key=lambda f: (f["combustible"], f["ubicacion"])
    )
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    with HISTORIAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(nuevo)

    actuales = sorted(filas_hoy.values(), key=lambda f: (f["combustible"], f["ubicacion"]))
    ACTUALES.write_text(
        json.dumps({"fecha_consulta": hoy, "precios": actuales}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return actuales


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--descubrir", action="store_true", help="muestra lo encontrado sin guardar nada")
    parser.add_argument("--fecha", help="fecha de consulta AAAA-MM-DD (por defecto, hoy en Lima)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hoy = args.fecha or datetime.now(ZONA).date().isoformat()
    precios, paginas = recorrer(URLS_INICIO, nueva_sesion())
    log.info("Páginas leídas: %d | precios de diésel encontrados: %d", len(paginas), len(precios))

    if args.descubrir:
        for url in paginas:
            print("PÁGINA ", url)
        for p in sorted(precios, key=lambda p: (p.combustible, p.ubicacion)):
            print(f"{p.combustible:18} {p.ubicacion[:35]:35} S/ {p.precio:7.2f}  {p.fuente}")
        return 0

    if not precios:
        log.warning("No se obtuvieron precios hoy; se usarán los últimos registrados.")
    actuales = registrar(precios, hoy)
    if not actuales:
        log.error("No hay precios de hoy ni historial previo. Revise la URL con --descubrir.")
        return 1

    for f in actuales:
        print(f"{f['combustible']:18} {f['ubicacion'][:35]:35} S/ {f['precio']:>7}  "
              f"{f['estado']:17} (precio desde {f['fecha_precio']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

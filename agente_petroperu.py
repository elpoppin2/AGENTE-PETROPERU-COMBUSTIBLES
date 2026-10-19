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
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URLS_INICIO = os.environ.get(
    "PETROPERU_URLS",
    "https://www.petroperu.com.pe/productos/lista-de-precios-en-nuestras-plantas/",
).split(",")
DOMINIOS_PERMITIDOS = ("petroperu.com.pe",)
PALABRAS_ENLACE = ("precio", "lista", "combustible", "tarifa")
MAX_PAGINAS = int(os.environ.get("PETROPERU_MAX_PAGINAS", "40"))
MAX_PROFUNDIDAD = 2
ZONA = ZoneInfo("America/Lima")

DIR_DATOS = Path(os.environ.get("PETROPERU_DATOS", Path(__file__).parent / "data"))
HISTORIAL = DIR_DATOS / "historial.csv"
ACTUALES = DIR_DATOS / "precios_actuales.json"
LISTAS = DIR_DATOS / "listas.csv"
EXCEL = DIR_DATOS / "precios-diesel-petroperu.xlsx"  # descarga del tablero
DIR_REPORTES = Path(os.environ.get("PETROPERU_REPORTES", Path(__file__).parent / "reportes"))
URL_TABLERO = "https://elpoppin2.github.io/AGENTE-PETROPERU-COMBUSTIBLES/"
USUARIO_AVISO = os.environ.get("PETROPERU_AVISAR_A", "elpoppin2")  # se le menciona en el aviso  # un precio por lista publicada (para gráficos)
COLUMNAS_LISTAS = ["vigencia", "combustible", "ubicacion", "precio", "fuente"]
COLUMNAS = [
    "fecha_consulta", "combustible", "ubicacion", "precio", "estado",
    "fecha_precio", "fuente",
]

# Sólo se registran estos dos diésel. El orden importa: el primer patrón que
# coincide gana, así "B5 S-50 UV" no se confunde con el "B5 S-50" a secas.
# En los PDF de Petroperú aparecen como "DIESEL B5 UV S-50" y "DIESEL B5 S-50"
# (Addendum N° 1); también se aceptan "Diesel B5-S50UV", "DB5 S-50" o
# "Diesel B5 S-50 (Uso Vehicular)". "DIESEL B5 UV" sin S-50 no se registra.
_B5 = r"(?:diesel\s*(?:db)?\s*|\bd)b5"
_S50 = r"s\W*50"
COMBUSTIBLES = [
    ("DIESEL_B5_S50_UV", _B5 + r"\W*(?:uv\W*" + _S50 + "|" + _S50 + r"\W*(?:uv|.*uso\s*vehicular))"),
    ("DIESEL_B5_S50", _B5 + r"\W*" + _S50),
]
# "G. E." = precio para generadoras eléctricas (Addendum N° 2), no automotor.
EXCLUIR = re.compile(r"industrial|marino|turbo|residual|aviacion|jet|asfalto|solvente|\bg\s*\.\s*e\b|generador")
VIGENCIA = re.compile(r"vigencia\s+a\s+partir\s+del\s+(\d{2})\.(\d{2})\.(\d{4})", re.I)
NUMERO = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,4}))(?![\d.,])")
PRECIO_MIN, PRECIO_MAX = 1.0, 100.0  # soles por galón/kg razonables

log = logging.getLogger("agente_petroperu")


@dataclass
class Precio:
    combustible: str
    ubicacion: str
    precio: float
    fuente: str
    vigencia: str | None = None  # fecha AAAA-MM-DD desde la que rige el precio


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
    # El encabezado puede ocupar varias filas (en los PDF de Petroperú
    # "DIESEL B5 UV S-50" está una fila debajo de "PLANTAS"): se unen por
    # columna todas las filas anteriores a la primera que tiene precios.
    inicio = next((k for k, f in enumerate(filas) if any(a_precio(c) is not None for c in f)), len(filas))
    ancho = max(len(f) for f in filas)
    encabezado = [" ".join(f[i] for f in filas[:inicio] if i < len(f) and f[i]) for i in range(ancho)]
    datos = filas[inicio:]
    resultado: list[Precio] = []

    combustibles_en_encabezado = [identificar_combustible(c) for c in encabezado]
    if any(combustibles_en_encabezado):
        # Combustibles como columnas; cada fila es una ubicación/planta.
        for fila in datos:
            etiqueta = next((c for c in fila if c and a_precio(c) is None), "")
            ubicacion = limpiar_ubicacion(etiqueta, ubicacion_defecto)
            for i, celda in enumerate(fila):
                clave = combustibles_en_encabezado[i] if i < len(combustibles_en_encabezado) else None
                valor = a_precio(celda)
                if clave and valor is not None:
                    resultado.append(Precio(clave, ubicacion, valor, fuente))
        return resultado

    # Combustibles como filas; cada columna numérica es una ubicación/planta.
    # El nombre del producto puede venir partido en varias celdas
    # ("Diesel B5" | "S-50 UV"), así que se unen las celdas previas al primer precio.
    for fila in datos:
        idx = next((i for i, c in enumerate(fila) if a_precio(c) is not None), len(fila))
        clave = identificar_combustible(" ".join(fila[:idx]))
        if clave is None:
            continue
        for i, celda in enumerate(fila[idx:], start=idx):
            valor = a_precio(celda)
            if valor is None:
                continue
            columna = encabezado[i] if i < len(encabezado) else ""
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
    # La primera "VIGENCIA A PARTIR DEL dd.mm.aaaa" es la de esta lista (al pie
    # aparece también la de la lista anterior).
    m = VIGENCIA.search("\n".join(texto_total))
    if m:
        for p in precios:
            p.vigencia = p.vigencia or f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return precios


def listas_automotrices(html: str, base: str) -> list[tuple[str, str]]:
    """Listas "Automotriz" de la página de Petroperú, de la más reciente a la más antigua.

    Cada lista es un <li data-date="AAAA-MM-DD"> con el título "Automotriz" y
    un enlace al PDF; las demás categorías (Marino, Aviación, Asfaltos...) se ignoran.
    """
    listas = []
    for li in BeautifulSoup(html, "html.parser").select("li[data-date]"):
        titulo = li.select_one(".title")
        enlace = li.find("a", href=True)
        if titulo and enlace and normalizar(titulo.get_text()) == "automotriz":
            listas.append((li["data-date"], urljoin(base, enlace["href"])))
    return sorted(listas, reverse=True)


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
    """Visita la página de precios y lee la lista automotriz vigente.

    Si la página no tiene el formato conocido de Petroperú, sigue cada enlace
    de precios que encuentre (páginas HTML o PDF) como respaldo.
    """
    for url in urls_inicio:
        r = descargar(sesion, url.strip())
        if r is None:
            continue
        listas = listas_automotrices(r.text, r.url)
        if not listas:
            continue
        fecha, url_pdf = listas[0]
        log.info("Lista automotriz vigente: %s (%s); %d listas publicadas", fecha, url_pdf, len(listas))
        pdf = descargar(sesion, url_pdf)
        if pdf is None:
            return [], [r.url]
        try:
            precios = extraer_pdf(pdf.content, url_pdf, "General")
        except Exception as e:
            log.error("No se pudo leer el PDF %s: %s", url_pdf, e)
            return [], [r.url, url_pdf]
        for p in precios:
            p.vigencia = fecha
        log.info("PDF  %s -> %d precios", url_pdf, len(precios))
        return deduplicar(precios), [r.url, url_pdf]
    return recorrer_enlaces(urls_inicio, sesion)


def recorrer_enlaces(urls_inicio: list[str], sesion: requests.Session) -> tuple[list[Precio], list[str]]:
    """Respaldo: visita la página de precios y cada enlace de precios que contiene."""
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
        if p.vigencia:
            fecha_precio = p.vigencia
        else:
            fecha_precio = previo["fecha_precio"] if sin_cambio else hoy
        filas_hoy[(p.combustible, p.ubicacion)] = {
            "fecha_consulta": hoy,
            "combustible": p.combustible,
            "ubicacion": p.ubicacion,
            "precio": f"{p.precio:.4f}",
            "estado": "sin_cambio" if sin_cambio else "actualizado",
            "fecha_precio": fecha_precio,
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


def guardar_listas(precios: list[Precio]) -> int:
    """Agrega a data/listas.csv los precios de cada lista publicada por Petroperú.

    Si ya existe un precio para la misma vigencia, combustible y planta, se
    reemplaza (Petroperú a veces publica una corrección el mismo día).
    """
    filas: dict[tuple[str, str, str], dict] = {}
    if LISTAS.exists():
        with LISTAS.open(newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                filas[(fila["vigencia"], fila["combustible"], fila["ubicacion"])] = fila
    nuevos = 0
    for p in precios:
        if not p.vigencia:
            continue
        clave = (p.vigencia, p.combustible, p.ubicacion)
        nuevos += clave not in filas
        filas[clave] = {"vigencia": p.vigencia, "combustible": p.combustible, "ubicacion": p.ubicacion,
                        "precio": f"{p.precio:.4f}", "fuente": p.fuente}
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    with LISTAS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_LISTAS)
        w.writeheader()
        w.writerows(filas[k] for k in sorted(filas))
    return nuevos


def vigencias_registradas() -> set[str]:
    if not LISTAS.exists():
        return set()
    with LISTAS.open(newline="", encoding="utf-8") as f:
        return {fila["vigencia"] for fila in csv.DictReader(f)}


NOMBRES = {"DIESEL_B5_S50_UV": "Diésel B5 S-50 UV", "DIESEL_B5_S50": "Diésel B5 S-50"}
MESES = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "set.", "oct.", "nov.", "dic."]


def fecha_larga(iso: str) -> str:
    a, m, d = iso.split("-")
    return f"{int(d)} {MESES[int(m) - 1]} {a}"


def reporte_cambio(vigencia: str) -> tuple[str, str, str] | None:
    """Arma el reporte de una lista frente a la anterior.

    Devuelve (título, cuerpo en Markdown, mensaje corto para WhatsApp).

    Devuelve None si no hay lista anterior con la que comparar.
    """
    listas: dict[str, dict[tuple[str, str], dict]] = {}
    with LISTAS.open(newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            listas.setdefault(fila["vigencia"], {})[(fila["combustible"], fila["ubicacion"])] = fila
    fechas = sorted(listas)
    if vigencia not in listas or fechas.index(vigencia) == 0:
        return None
    anterior = fechas[fechas.index(vigencia) - 1]
    nueva, vieja = listas[vigencia], listas[anterior]
    fuente = next(iter(nueva.values()))["fuente"]

    def variacion(clave):
        if clave not in nueva:
            return None
        n = float(nueva[clave]["precio"])
        v = float(vieja[clave]["precio"]) if clave in vieja else None
        return n, v, (n - v if v is not None else None)

    resumen, filas_tabla, corto = [], [], []
    for comb, nombre in NOMBRES.items():
        difs = [x[2] for k in nueva if k[0] == comb and (x := variacion(k)) and x[2] is not None]
        suben = sum(d > 0.00005 for d in difs); bajan = sum(d < -0.00005 for d in difs)
        corto.append(f"{nombre}: ▲ {suben} · ▼ {bajan} · = {len(difs) - suben - bajan} plantas")
        if suben or bajan:
            rango = sorted({round(d, 4) for d in difs if abs(d) > 0.00005})
            montos = " a ".join(f"{d:+.4f}" for d in (rango[0], rango[-1])) if len(rango) > 1 else f"{rango[0]:+.4f}"
            resumen.append(f"- **{nombre}**: " + ", ".join(
                t for t in (f"▲ subió en {suben} plantas" if suben else "", f"▼ bajó en {bajan} plantas" if bajan else "",
                            f"sin cambio en {len(difs) - suben - bajan}" if len(difs) - suben - bajan else "") if t)
                           + f" (S/ {montos} por galón).")
        else:
            resumen.append(f"- **{nombre}**: sin cambios.")

    def celda(clave):
        x = variacion(clave)
        if not x:
            return "—", "—"
        n, v, d = x
        if d is None:
            return f"{n:.4f}", "nuevo"
        if abs(d) <= 0.00005:
            return f"{n:.4f}", "= sin cambio"
        return f"{n:.4f}", f"{'▲' if d > 0 else '▼'} {d:+.4f}"

    plantas = sorted({k[1] for k in nueva})
    for planta in plantas:
        uv, uv_d = celda(("DIESEL_B5_S50_UV", planta))
        s50, s50_d = celda(("DIESEL_B5_S50", planta))
        filas_tabla.append(f"| {planta.title()} | {uv} | {uv_d} | {s50} | {s50_d} |")

    callao = variacion(("DIESEL_B5_S50_UV", "CALLAO"))
    detalle = ""
    if callao and callao[2] is not None and abs(callao[2]) > 0.00005:
        detalle = f" (B5 S-50 UV Callao {'▲' if callao[2] > 0 else '▼'} {callao[2]:+.2f})"
    titulo = f"Cambio de precios Petroperú: lista del {fecha_larga(vigencia)}{detalle}"
    en_callao = []
    for comb, nombre in NOMBRES.items():
        x = variacion((comb, "CALLAO"))
        if x and x[2] is not None:
            f = "▲" if x[2] > 0.00005 else "▼" if x[2] < -0.00005 else "="
            en_callao.append(f"{nombre.replace('Diésel ', '')} S/ {x[0]:.2f} ({f} {x[2]:+.2f})")
    mensaje = "\n".join([
        f"⛽ *Petroperú: nueva lista del {fecha_larga(vigencia)}*",
        *(["Callao: " + " · ".join(en_callao)] if en_callao else []),
        *corto,
        f"Detalle: {URL_TABLERO}",
    ])
    cuerpo = "\n".join([
        f"## Nueva lista de precios Petroperú, vigente desde el {fecha_larga(vigencia)}",
        "",
        f"Comparada con la lista anterior, del {fecha_larga(anterior)}. Precios de lista con impuestos, "
        "en soles por galón, sin descuentos ni FISE.",
        "",
        *resumen,
        "",
        "| Planta | B5 S-50 UV | Variación | B5 S-50 | Variación |",
        "|---|---:|---:|---:|---:|",
        *filas_tabla,
        "",
        f"[Ver el tablero]({URL_TABLERO}) · [PDF de Petroperú]({fuente})",
        "",
        f"_Aviso automático del agente de precios. cc @{USUARIO_AVISO}_",
    ])
    return titulo, cuerpo, mensaje


def escribir_reporte(vigencia: str) -> Path | None:
    """Guarda el reporte en reportes/AAAA-MM-DD.md y lo anuncia a GitHub Actions."""
    rep = reporte_cambio(vigencia)
    if rep is None:
        return None
    titulo, cuerpo, _ = rep
    DIR_REPORTES.mkdir(parents=True, exist_ok=True)
    ruta = DIR_REPORTES / f"{vigencia}.md"
    ruta.write_text(f"# {titulo}\n\n{cuerpo}\n", encoding="utf-8")
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"reporte={ruta}\ntitulo={titulo}\n")
    log.info("Reporte de cambio de precios: %s", ruta)
    return ruta


def markdown_a_html(md: str) -> str:
    """Convierte el Markdown sencillo de los reportes (títulos, viñetas, tabla, enlaces) a HTML."""
    import html as _html

    def en_linea(t: str) -> str:
        t = _html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
        return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", t)

    partes, en_lista, tabla = [], False, []
    celda = "padding:4px 10px;border-bottom:1px solid #ddd;text-align:{}"
    for linea in md.splitlines() + [""]:
        if linea.startswith("|"):
            if not re.fullmatch(r"\|[-:| ]+\|", linea):
                tabla.append([c.strip() for c in linea.strip("|").split("|")])
            continue
        if tabla:
            cab, *filas = tabla
            th = "".join(f'<th style="{celda.format("left" if i == 0 else "right")}">{en_linea(c)}</th>' for i, c in enumerate(cab))
            trs = "".join("<tr>" + "".join(
                f'<td style="{celda.format("left" if i == 0 else "right")};color:'
                f'{"#b54708" if c.startswith("▲") else "#067647" if c.startswith("▼") else "inherit"}">{en_linea(c)}</td>'
                for i, c in enumerate(f)) + "</tr>" for f in filas)
            partes.append(f'<table style="border-collapse:collapse;font-size:14px"><tr>{th}</tr>{trs}</table>')
            tabla = []
        if linea.startswith("- "):
            if not en_lista:
                partes.append("<ul>"); en_lista = True
            partes.append(f"<li>{en_linea(linea[2:])}</li>")
            continue
        if en_lista:
            partes.append("</ul>"); en_lista = False
        if linea.startswith("## "):
            partes.append(f"<h2>{en_linea(linea[3:])}</h2>")
        elif linea.strip():
            partes.append(f"<p>{en_linea(linea)}</p>")
    return '<div style="font-family:Arial,sans-serif;font-size:15px;color:#111">' + "".join(partes) + "</div>"


def enviar_avisos(vigencia: str, enlace: str | None = None) -> bool:
    """Envía el reporte por correo y WhatsApp a los destinatarios configurados.

    Se configura con variables de entorno (en GitHub, como *secrets* del repositorio):
      AVISO_CORREO_USUARIO / AVISO_CORREO_CLAVE  cuenta que envía (Gmail: contraseña de aplicación)
      AVISO_CORREOS                              destinatarios, separados por comas
      AVISO_CORREO_SERVIDOR                      opcional, por defecto smtp.gmail.com
      AVISO_WHATSAPP                             telefono:apikey de CallMeBot, separados por comas
    Lo que no esté configurado se omite. Devuelve False si algún envío falló.
    """
    import smtplib
    from email.message import EmailMessage

    rep = reporte_cambio(vigencia)
    if rep is None:
        log.warning("No hay reporte para la lista %s", vigencia)
        return True
    titulo, cuerpo, mensaje = rep
    if enlace:
        cuerpo += f"\n\n[Ver el aviso en GitHub]({enlace})"
    ok = True

    usuario, clave = os.environ.get("AVISO_CORREO_USUARIO"), os.environ.get("AVISO_CORREO_CLAVE")
    destinos = [c.strip() for c in os.environ.get("AVISO_CORREOS", "").split(",") if c.strip()]
    if usuario and clave and destinos:
        correo = EmailMessage()
        correo["Subject"], correo["From"], correo["To"] = titulo, usuario, ", ".join(destinos)
        correo.set_content(cuerpo)
        correo.add_alternative(markdown_a_html(cuerpo), subtype="html")
        try:
            with smtplib.SMTP_SSL(os.environ.get("AVISO_CORREO_SERVIDOR", "smtp.gmail.com"), 465, timeout=30) as smtp:
                smtp.login(usuario, clave)
                smtp.send_message(correo)
            log.info("Correo enviado a %d destinatarios", len(destinos))
        except Exception as e:
            log.error("No se pudo enviar el correo: %s", e)
            ok = False
    else:
        log.info("Correo no configurado; se omite")

    contactos = [c.strip() for c in os.environ.get("AVISO_WHATSAPP", "").split(",") if ":" in c]
    for contacto in contactos:
        telefono, apikey = (x.strip() for x in contacto.split(":", 1))
        url = (f"https://api.callmebot.com/whatsapp.php?phone={quote(telefono)}"
               f"&text={quote(mensaje)}&apikey={quote(apikey)}")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            log.info("WhatsApp enviado a ...%s", telefono[-3:])
        except requests.RequestException as e:
            log.error("No se pudo enviar el WhatsApp a ...%s: %s", telefono[-3:], type(e).__name__)
            ok = False
        time.sleep(2)  # CallMeBot limita la frecuencia de mensajes
    if not contactos:
        log.info("WhatsApp no configurado; se omite")
    return ok


def generar_excel() -> Path | None:
    """Crea el Excel con todo el histórico de data/listas.csv.

    Hojas: precios vigentes por planta, histórico de cada diésel (una columna
    por planta) y los datos en formato tabla, con su PDF de origen.
    """
    from datetime import date
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    if not LISTAS.exists():
        return None
    with LISTAS.open(newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    if not filas:
        return None
    fecha = lambda iso: date.fromisoformat(iso)
    plantas = sorted({r["ubicacion"] for r in filas})
    vigencias = sorted({r["vigencia"] for r in filas})
    precio = {(r["vigencia"], r["combustible"], r["ubicacion"]): float(r["precio"]) for r in filas}
    ultimo: dict[tuple[str, str], tuple[str, float]] = {}
    for r in sorted(filas, key=lambda r: r["vigencia"]):
        ultimo[(r["combustible"], r["ubicacion"])] = (r["vigencia"], float(r["precio"]))

    rojo = PatternFill("solid", fgColor="E60000")
    cabecera = Font(bold=True, color="FFFFFF")
    titulo = Font(bold=True, size=14)
    num, fmt_fecha = "0.0000", "dd/mm/yyyy"

    def encabezar(ws, fila, valores, anchos):
        for i, v in enumerate(valores, start=1):
            c = ws.cell(row=fila, column=i, value=v)
            c.fill, c.font = rojo, cabecera
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, w in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    wb = Workbook()
    ws = wb.active
    ws.title = "Precios vigentes"
    ws["A1"] = "Precios de lista del diésel en plantas de Petroperú"
    ws["A1"].font = titulo
    ws["A2"] = (f"Soles por galón, con impuestos, sin descuentos ni FISE. Lista vigente desde el "
                f"{fecha(vigencias[-1]).strftime('%d/%m/%Y')}. Fuente: Petroperú (Addendum N° 1).")
    encabezar(ws, 4, ["Planta", "B5 S-50 UV", "Vigente desde", "B5 S-50", "Vigente desde"], [18, 14, 14, 14, 14])
    for i, planta in enumerate(plantas, start=5):
        ws.cell(row=i, column=1, value=planta.title())
        for j, comb in enumerate(("DIESEL_B5_S50_UV", "DIESEL_B5_S50")):
            if (comb, planta) in ultimo:
                v, pr = ultimo[(comb, planta)]
                ws.cell(row=i, column=2 + 2 * j, value=pr).number_format = num
                ws.cell(row=i, column=3 + 2 * j, value=fecha(v)).number_format = fmt_fecha
    ws.freeze_panes = "B5"

    for comb, nombre in NOMBRES.items():
        h = wb.create_sheet(f"Histórico {nombre.replace('Diésel ', '')}")
        encabezar(h, 1, ["Vigencia", *(p.title() for p in plantas)], [12, *([13] * len(plantas))])
        for i, v in enumerate(reversed(vigencias), start=2):  # la más reciente arriba
            h.cell(row=i, column=1, value=fecha(v)).number_format = fmt_fecha
            for j, planta in enumerate(plantas, start=2):
                if (v, comb, planta) in precio:
                    h.cell(row=i, column=j, value=precio[(v, comb, planta)]).number_format = num
        h.freeze_panes = "B2"
        h.auto_filter.ref = f"A1:{get_column_letter(len(plantas) + 1)}{len(vigencias) + 1}"

    d = wb.create_sheet("Datos")
    encabezar(d, 1, ["Vigencia", "Combustible", "Planta", "Precio (S/ por galón)", "PDF de Petroperú"], [12, 20, 18, 14, 60])
    ordenadas = sorted(sorted(filas, key=lambda r: (r["combustible"], r["ubicacion"])), key=lambda r: r["vigencia"], reverse=True)
    for i, r in enumerate(ordenadas, start=2):  # la lista más reciente arriba
        d.cell(row=i, column=1, value=fecha(r["vigencia"])).number_format = fmt_fecha
        d.cell(row=i, column=2, value=NOMBRES.get(r["combustible"], r["combustible"]))
        d.cell(row=i, column=3, value=r["ubicacion"].title())
        d.cell(row=i, column=4, value=float(r["precio"])).number_format = num
        d.cell(row=i, column=5, value=r["fuente"])
    d.freeze_panes = "A2"
    d.auto_filter.ref = f"A1:E{len(filas) + 1}"

    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    wb.save(EXCEL)
    log.info("Excel actualizado: %s (%d precios)", EXCEL, len(filas))
    return EXCEL


def historico(desde: str, sesion: requests.Session) -> list[Precio]:
    """Lee todas las listas "Automotriz" publicadas desde la fecha indicada."""
    r = descargar(sesion, URLS_INICIO[0].strip())
    if r is None:
        return []
    listas = sorted(l for l in listas_automotrices(r.text, r.url) if l[0] >= desde)
    log.info("Listas automotrices desde %s: %d", desde, len(listas))
    precios: list[Precio] = []
    for fecha, url_pdf in listas:  # de la más antigua a la más reciente
        pdf = descargar(sesion, url_pdf)
        hallados: list[Precio] = []
        if pdf is not None:
            try:
                hallados = deduplicar(extraer_pdf(pdf.content, url_pdf, "General"))
            except Exception as e:
                log.error("No se pudo leer el PDF %s: %s", url_pdf, e)
        for p in hallados:
            p.vigencia = fecha
        resumen = {c: sum(p.combustible == c for p in hallados) for c, _ in COMBUSTIBLES}
        nivel = logging.INFO if all(resumen.values()) else logging.WARNING
        log.log(nivel, "LISTA %s %s %s", fecha, resumen, url_pdf)
        precios += hallados
        time.sleep(0.5)  # no saturar la web de Petroperú
    return precios


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--descubrir", action="store_true", help="muestra lo encontrado sin guardar nada")
    parser.add_argument("--fecha", help="fecha de consulta AAAA-MM-DD (por defecto, hoy en Lima)")
    parser.add_argument("--historico", metavar="DESDE",
                        help="carga en data/listas.csv todas las listas desde AAAA-MM-DD y termina")
    parser.add_argument("--reporte", metavar="VIGENCIA",
                        help="genera el reporte de la lista AAAA-MM-DD (o 'ultima') frente a la anterior y termina")
    parser.add_argument("--enviar", metavar="VIGENCIA",
                        help="envía por correo y WhatsApp el reporte de la lista AAAA-MM-DD y termina")
    parser.add_argument("--enlace", help="enlace al aviso en GitHub para incluir en el correo")
    parser.add_argument("--excel", action="store_true", help="solo regenera el Excel del histórico y termina")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.excel:
        return 0 if generar_excel() else 1

    if args.enviar:
        return 0 if enviar_avisos(args.enviar, args.enlace) else 1

    if args.historico:
        precios = historico(args.historico, nueva_sesion())
        nuevos = guardar_listas(precios)
        generar_excel()
        log.info("Histórico: %d precios leídos, %d nuevos en %s", len(precios), nuevos, LISTAS)
        return 0 if precios else 1

    if args.reporte:
        vigencia = max(vigencias_registradas(), default=None) if args.reporte == "ultima" else args.reporte
        ruta = escribir_reporte(vigencia) if vigencia else None
        if ruta:
            print(ruta.read_text(encoding="utf-8"))
        return 0 if ruta else 1

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
    conocidas = vigencias_registradas()
    guardar_listas(precios)
    generar_excel()
    # Si Petroperú publicó una lista nueva, se prepara el reporte para el aviso.
    nuevas = sorted({p.vigencia for p in precios if p.vigencia} - conocidas)
    if nuevas and conocidas:
        escribir_reporte(nuevas[-1])
    if not actuales:
        log.error("No hay precios de hoy ni historial previo. Revise la URL con --descubrir.")
        return 1

    for f in actuales:
        print(f"{f['combustible']:18} {f['ubicacion'][:35]:35} S/ {f['precio']:>7}  "
              f"{f['estado']:17} (precio desde {f['fecha_precio']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

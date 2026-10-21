"""Exploración temporal: ¿traen ISC los PDF antiguos de Petroperú y la tabla por planta los de Osinergmin?"""
import io, pathlib, datetime as dt, requests, pdfplumber
OUT = pathlib.Path("explorar/salida"); OUT.mkdir(parents=True, exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0"
lineas = []
for url in pathlib.Path("explorar/petroperu_muestra.txt").read_text().split():
    r = s.get(url, timeout=60)
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ""
            if "S-50" in t:
                lineas.append(f"=== PETROPERU {url} pag {i}")
                lineas += [l for l in t.splitlines() if any(k in l for k in ("I S C", "ISC", "I.S.C", "S-50", "VIGENCIA", "IGV", "I G V"))]
base = "https://www.osinergmin.gob.pe/seccion/centro_documental/gart/PreciosReferencia/"
for inicio in (dt.date(2023, 1, 2), dt.date(2024, 3, 4), dt.date(2025, 5, 5)):
    for k in range(0, 10):
        d = inicio + dt.timedelta(days=k)
        r = s.get(base + f"PrecioReferencia{d:%d%m%Y}.pdf", timeout=30)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                lineas.append(f"=== OSINERGMIN {d} paginas={len(pdf.pages)}")
                for p in pdf.pages[1:]:
                    lineas += (p.extract_text() or "").splitlines()[:30]
            break
    else:
        lineas.append(f"=== OSINERGMIN sin PDF cerca de {inicio}")
(OUT / "isc.txt").write_text("\n".join(lineas))

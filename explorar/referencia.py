"""Exploración temporal: descarga los últimos PDF de precios de referencia de Osinergmin."""
import io, json, pathlib, datetime as dt, requests, pdfplumber
OUT = pathlib.Path("explorar/salida"); OUT.mkdir(parents=True, exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0"
base = "https://www.osinergmin.gob.pe/seccion/centro_documental/gart/PreciosReferencia/"
notas = []
for pagina in ["https://www.osinergmin.gob.pe/seccion/institucional/regulacion-tarifaria/precios-referencia",
               base]:
    try:
        r = s.get(pagina, timeout=30); notas.append(f"{pagina} -> {r.status_code} {len(r.text)}")
        (OUT / ("idx_" + str(abs(hash(pagina)) % 1000) + ".html")).write_text(r.text[:200000])
    except Exception as e:
        notas.append(f"{pagina} ERROR {e}")
hoy = dt.date(2026, 10, 21); bajados = 0
for k in range(0, 60):
    d = hoy - dt.timedelta(days=k)
    url = base + f"PrecioReferencia{d:%d%m%Y}.pdf"
    try:
        r = s.get(url, timeout=30)
    except Exception as e:
        notas.append(f"{url} ERROR {e}"); continue
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        notas.append(f"OK {url} {len(r.content)}")
        (OUT / f"ref_{d:%Y%m%d}.pdf").write_bytes(r.content)
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            info = [{"texto": p.extract_text(), "tablas": p.extract_tables()} for p in pdf.pages]
        (OUT / f"ref_{d:%Y%m%d}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
        bajados += 1
        if bajados >= 2: break
(OUT / "referencia_notas.txt").write_text("\n".join(notas))

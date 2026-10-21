import sys, pathlib, requests, pdfplumber, io
sys.path.insert(0, "explorar")
import agente_main as a
OUT = pathlib.Path("explorar/salida"); s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0"
lineas = []
for d in ["03062024", "14102024", "18112024", "09122024", "30012023"]:
    r = s.get(a.URL_OSINERGMIN.replace("{:%d%m%Y}", d), timeout=30)
    lineas.append(f"===== {d} {r.status_code} {len(r.content)}")
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for i, p in enumerate(pdf.pages):
            t1 = p.extract_text() or ""
            t2 = a._renglones(p)
            lineas.append(f"--- pag {i} (texto normal, 15 renglones)"); lineas += t1.splitlines()[:15]
            lineas.append(f"--- pag {i} (por posición, 30 renglones)"); lineas += t2.splitlines()[:30]
(OUT / "faltantes.txt").write_text("\n".join(lineas))
# reintento

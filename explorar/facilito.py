"""Exploración temporal: qué peticiones hace Facilito (Osinergmin) y qué devuelve."""
import json, pathlib, asyncio
from playwright.async_api import async_playwright

OUT = pathlib.Path("explorar/salida"); OUT.mkdir(parents=True, exist_ok=True)
URLS = [
    "https://www.facilito.gob.pe/facilito/pages/facilito/buscadorEESS.jsp",
    "https://www.facilito.gob.pe/facilito/",
    "https://www.osinergmin.gob.pe/seccion/institucional/regulacion-tarifaria/publicaciones/hidrocarburos",
]

async def main():
    reg = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        async def resp(r):
            try:
                ct = r.headers.get("content-type", "")
                cuerpo = (await r.text())[:1500] if any(k in ct for k in ("json", "xml", "text/plain", "javascript")) else ""
            except Exception:
                cuerpo = ""
            reg.append({"url": r.url, "metodo": r.request.method, "estado": r.status, "tipo": ct,
                        "post": (r.request.post_data or "")[:800], "cuerpo": cuerpo})
        pg.on("response", lambda r: asyncio.ensure_future(resp(r)))
        for i, u in enumerate(URLS):
            try:
                await pg.goto(u, wait_until="networkidle", timeout=60000)
                await pg.wait_for_timeout(3000)
                (OUT / f"pagina{i}.html").write_text(await pg.content())
                await pg.screenshot(path=str(OUT / f"pagina{i}.png"), full_page=True)
                # Intentar una búsqueda: primer select con opciones (departamento) y botón buscar
                if i == 0:
                    sels = await pg.query_selector_all("select")
                    info = []
                    for s in sels:
                        opts = await s.eval_on_selector_all("option", "els => els.map(e => [e.value, e.textContent.trim()])")
                        info.append({"id": await s.get_attribute("id"), "name": await s.get_attribute("name"), "opciones": opts[:60]})
                    (OUT / "selects.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
            except Exception as e:
                reg.append({"url": u, "error": str(e)})
        await b.close()
    (OUT / "red.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1))

asyncio.run(main())

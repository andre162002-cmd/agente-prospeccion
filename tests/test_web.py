import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from prospector.web.app import create_app


def client(agent, db, settings):
    return TestClient(create_app(settings, db, agent_factory=lambda: agent))


def test_pages_and_flows(agent, db, settings):
    agent.run(db.create_run("Encuentra 10 cafeterías en Medellín"))
    c = client(agent, db, settings)
    for url in ["/", "/buscar", "/prospectos", "/prospectos?sector=cafeteria&orden=nombre", "/prospectos?q=laurel",
                "/mensajes", "/mensajes?estado=", "/duplicados", "/importar", "/cumplimiento", "/configuracion",
                "/prospectos/nuevo", "/corridas/1"]:
        r = c.get(url)
        assert r.status_code == 200, url
    p = next(p for p in db.list_prospects() if p["nombre"] == "Café Laurel")
    r = c.get(f"/prospectos/{p['id']}")
    assert r.status_code == 200 and "Ficha comercial" in r.text and "Por qué tiene" in r.text

    # Cambio de estado y actualización de datos
    r = c.post(f"/prospectos/{p['id']}/estado", data={"estado": "Reunión programada", "nota": "jueves"})
    assert r.status_code == 200 and db.get_prospect(p["id"])["estado_comercial"] == "Reunión programada"
    c.post(f"/prospectos/{p['id']}/actualizar", data={"razon_social": "Café Laurel S.A.S.", "fuente": "RUT entregado por el cliente"})
    assert db.get_prospect(p["id"])["razon_social"] == "Café Laurel S.A.S."

    # Mensajes: aprobar y marcar enviado desde la interfaz
    m = next(m for m in db.messages(p["id"]) if m["canal"] == "whatsapp")
    c.post(f"/mensajes/{m['id']}/editar", data={"cuerpo": m["cuerpo"] + " Saludos.", "origen": "ficha"})
    c.post(f"/mensajes/{m['id']}/aprobar", data={})
    assert db.get_message(m["id"])["estado"] == "aprobado"
    c.post(f"/mensajes/{m['id']}/enviado", data={})
    assert db.get_message(m["id"])["estado"] == "enviado"

    # Exportaciones
    r = c.get("/exportar.csv?sector=cafeteria")
    assert r.status_code == 200 and "Café Laurel" in r.content.decode("utf-8-sig")
    r = c.get("/exportar.xlsx")
    wb = load_workbook(io.BytesIO(r.content))
    header = [x.value for x in wb.active[1]]
    for col in ["ID", "Empresa", "Sector", "Ciudad", "Sitio web", "Redes sociales", "Contacto", "Cargo", "Correo",
                "Teléfono", "Servicio recomendado", "Problema potencial", "Justificación", "Puntaje", "Clasificación",
                "Fuentes", "Fecha de investigación", "Última actualización", "Estado comercial", "Observaciones"]:
        assert col in header

    # Importación CSV (exige fuente)
    csv_ok = "nombre,sector,ciudad,telefono,fuente\nHeladería Polo,heladeria,Bello,3105556677,Feria 2026\n"
    r = c.post("/importar", files={"archivo": ("x.csv", csv_ok, "text/csv")}, data={})
    assert r.status_code == 200 and db.find_prospect(nombre_norm="heladeria polo")
    csv_bad = "nombre,ciudad\nSin Fuente,Bello\n"
    r = c.post("/importar", files={"archivo": ("x.csv", csv_bad, "text/csv")}, data={})
    assert "fuente" in r.text

    # Exclusión y eliminación
    c.post(f"/prospectos/{p['id']}/excluir", data={"motivo": "Pidió no ser contactado"})
    assert db.suppressions()
    c.post(f"/prospectos/{p['id']}/eliminar")
    assert db.get_prospect(p["id"]) is None

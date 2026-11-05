from dataclasses import replace

from prospector import compliance
from prospector.agent.intel import PROHIBITED_PHRASES
from prospector.agent.llm import LLM
from prospector.agent.runner import ProspectingAgent


def test_website_research_extracts_public_channels(website):
    r = website.research("https://cafelaurel.co")
    assert r.ok and len(r.paginas) >= 2
    assert "hola@cafelaurel.co" in r.values("correo")
    assert "3001234567" in r.values("whatsapp")
    assert any("instagram.com/cafelaurel" in v for v in r.values("instagram"))
    assert r.values("formulario_contacto")
    assert "domicilios" in r.senales and "contratando" in r.senales
    assert r.precios_detectados >= 25
    assert any(v.startswith("María Gómez") for v in r.values("contacto"))
    for f in r.hallazgos:
        assert f.url.startswith("https://cafelaurel.co"), "cada dato debe tener URL de procedencia"


def test_website_respects_robots(website):
    r = website.research("https://bloqueado.co")
    assert not r.ok and r.bloqueado_por_robots and not r.hallazgos


def test_full_run(agent, db):
    rid = db.create_run("Encuentra 10 cafeterías en Medellín que puedan necesitar costeo de productos")
    report = agent.run(rid)
    run = db.get_run(rid)
    assert run["estado"] == "completada", run["log"]
    # 6 resultados: 1 repetido, 1 sede de otra empresa, 1 cerrado → 3 empresas nuevas
    assert report["resultados_fuente"] == 6
    assert report["empresas_nuevas"] == 3
    assert report["sedes_agregadas"] == 1
    assert report["cerradas"] == 1
    assert report["ya_existian"] == 1
    rows = {p["nombre"]: p for p in db.list_prospects(incluir_excluidos=True)}
    laurel = rows["Café Laurel"]
    assert laurel["num_sedes"] == 2
    assert laurel["whatsapp"] == "3001234567" and laurel["correo"] == "hola@cafelaurel.co"
    assert laurel["contacto_nombre"] == "María Gómez"
    assert laurel["puntaje"] >= 60 and laurel["estado_comercial"] == "Prospecto calificado"
    assert laurel["ficha"]["servicio_recomendado"] in agent.offer.services
    jv = rows["Juan Valdez Café"]
    assert jv["excluido"] == 1 and jv["estado_comercial"] == "Descartado"
    # Evidencia con fuente, fecha, confianza y verificación
    ev = db.evidence(laurel["id"])
    assert ev and all(e["fuente"] and e["fecha"] and e["confianza"] and e["verificacion"] for e in ev)
    # Mensajes: borradores solo para calificados
    msgs = db.messages(laurel["id"])
    assert {m["canal"] for m in msgs} >= {"whatsapp", "correo", "linkedin", "llamada", "preguntas_reunion", "propuesta_valor"}
    assert all(m["estado"] == "borrador" for m in msgs)
    assert not db.messages(jv["id"])
    wa = next(m for m in msgs if m["canal"] == "whatsapp")["cuerpo"]
    assert len(wa.split()) <= 90
    for m in msgs:
        assert not any(ph in m["cuerpo"].lower() for ph in PROHIBITED_PHRASES)
    # Segunda corrida: no duplica
    rid2 = db.create_run("Encuentra 10 cafeterías en Medellín")
    r2 = agent.run(rid2)
    assert r2["empresas_nuevas"] == 0 and db.count_prospects(incluir_excluidos=True) == 3


def test_run_without_places_key_reports_error(db, settings, offer, website):
    s = replace(settings, google_places_api_key=None)
    a = ProspectingAgent(db, s, offer=offer, website=website, llm=LLM(False, "x"))
    rid = db.create_run("Encuentra 10 cafeterías en Medellín")
    report = a.run(rid)
    assert db.get_run(rid)["estado"] == "error"
    assert "GOOGLE_PLACES_API_KEY" in report["error"]
    assert db.count_prospects(incluir_excluidos=True) == 0  # nunca inventa resultados


def test_compliance_flow(agent, db, offer):
    agent.run(db.create_run("Encuentra 10 cafeterías en Medellín"))
    p = next(p for p in db.list_prospects() if p["nombre"] == "Café Laurel")
    rules = offer.contact_rules
    wa = next(m for m in db.messages(p["id"]) if m["canal"] == "whatsapp")
    ok, _ = compliance.mark_sent(db, wa["id"], rules)
    assert not ok  # hay que aprobar primero
    assert compliance.approve_message(db, wa["id"], rules)[0]
    assert compliance.mark_sent(db, wa["id"], rules)[0]
    p = db.get_prospect(p["id"])
    assert p["estado_comercial"] == "Contactado" and p["intentos_contacto"] == 1
    # Frecuencia: no se puede volver a contactar antes de N días
    mail = next(m for m in db.messages(p["id"]) if m["canal"] == "correo")
    ok, reasons = compliance.approve_message(db, mail["id"], rules)
    assert not ok and "días" in reasons[0]
    # Exclusión: bloquea y evita reimportar
    compliance.opt_out(db, p)
    assert db.get_prospect(p["id"])["excluido"] == 1
    assert not [m for m in db.messages(p["id"]) if m["estado"] == "borrador"]
    pid, status = agent.ingest_manual({"nombre": "Café Laurel otra vez", "telefono": "300 123 4567", "fuente": "prueba"})
    assert pid is None and status == "excluido_lista"


def test_manual_ingest_and_merge(agent, db):
    a, s1 = agent.ingest_manual({"nombre": "Tienda Don José", "sector": "comercio_minorista", "ciudad": "Itagüí",
                                 "telefono": "3109998877", "fuente": "Visita al local"})
    b, s2 = agent.ingest_manual({"nombre": "Tienda Don Jose Ltda", "telefono": "3109998877", "correo": "ventas@donjose.co",
                                 "fuente": "Referido"})
    assert s1 == "nuevo" and s2 == "existente" and a == b
    assert db.get_prospect(a)["correo"] == "ventas@donjose.co"
    c, _ = agent.ingest_manual({"nombre": "Tienda Don Josee", "telefono": "3100000000", "fuente": "Feria"})
    assert any({x["a"]["id"], x["b"]["id"]} == {a, c} for x in db.possible_duplicates())
    db.merge_prospects(a, c)
    assert db.get_prospect(c) is None
    assert any(e["fuente"] == "Feria" for e in db.evidence(a))

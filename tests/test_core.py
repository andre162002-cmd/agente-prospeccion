from prospector.agent.planner import plan_instruction
from prospector.agent.qualify import score_prospect
from prospector.normalize import company_domain, normalize_name, normalize_phone


def test_normalize_name_and_ids():
    assert normalize_name("Café Laurel S.A.S.") == "cafe laurel"
    assert normalize_name("Café Laurel - Sede Envigado") == "cafe laurel"
    assert normalize_name("Pan & Café (Laureles)") == "pan y cafe"
    assert normalize_phone("+57 300 123 4567") == "3001234567"
    assert normalize_phone("(604) 444-1111") == "6044441111"
    assert normalize_phone("123") is None
    assert company_domain("https://www.cafelaurel.co/menu") == "cafelaurel.co"
    assert company_domain("https://instagram.com/cafelaurel") is None
    assert company_domain("https://linktr.ee/x") is None


def test_weights_sum_100(offer):
    assert sum(offer.weights().values()) == 100
    for sid in offer.raw["calificacion"]["pesos_por_servicio"]:
        assert sum(offer.weights(sid).values()) == 100, sid
        assert sid in offer.services


def test_offer_services_reference_valid_sectors(offer):
    for s in offer.services.values():
        for sec in s["sectores"]:
            assert sec in offer.sectors
    for sid, sec in offer.sectors.items():
        for n in sec.get("necesidades", []):
            assert n["servicio"] in offer.services


def test_planner_rules(offer):
    p = plan_instruction("Encuentra 50 restaurantes independientes en Medellín que puedan necesitar consultoría de costos y rentabilidad", offer)
    assert p.cantidad == 50 and p.sectores == ["restaurante"] and p.ciudades == ["Medellín"]
    assert p.servicio_objetivo == "diagnostico_rentabilidad" and p.consultas

    p = plan_instruction("Busca 30 empresas comerciales en Envigado y Sabaneta que puedan necesitar organización financiera", offer)
    assert p.cantidad == 30 and set(p.ciudades) == {"Envigado", "Sabaneta"}
    assert "comercio_minorista" in p.sectores
    assert p.servicio_objetivo == "costos_inventario_comercio"

    p = plan_instruction("Identifica cafeterías con varias sedes que puedan necesitar presupuestos y control de inventarios", offer)
    assert p.sectores == ["cafeteria"] and p.min_sedes == 2

    p = plan_instruction("Investiga 100 empresas del sector gastronómico en Medellín y el Valle de Aburrá. Prioriza cafeterías y restaurantes", offer)
    assert p.cantidad == 100 and len(p.ciudades) == len(offer.cities)
    assert {"cafeteria", "restaurante"} <= set(p.sectores)


def base(**kw):
    p = {"nombre": "Café Prueba", "sector": "cafeteria", "ciudad": "Medellín", "direccion": "Medellín, Antioquia, Colombia",
         "estado_negocio": "OPERATIONAL", "num_sedes": 1, "num_resenas": 80, "nivel_precio": "moderado", "senales": {}}
    p.update(kw)
    return p


def test_score_explained_and_bounded(offer):
    s = score_prospect(base(telefono="3001234567"), offer, "diagnostico_rentabilidad")
    assert 0 <= s["total"] <= 100
    assert set(s["criterios"]) == {"icp", "necesidad", "capacidad", "accesibilidad", "crecimiento", "geografia"}
    for c in s["criterios"].values():
        assert c["razones"], "cada criterio debe explicar su puntaje"
        assert c["puntos"] <= c["peso"]


def test_strong_vs_weak_and_exclusions(offer):
    strong = score_prospect(base(num_sedes=3, num_resenas=700, whatsapp="3001234567", correo="hola@x.co",
                                 senales={"domicilios": True, "contratando": True, "precios_detectados": 40},
                                 nivel_precio="alto", dominio="x.co"), offer, "diagnostico_rentabilidad")
    weak = score_prospect(base(ciudad="Bogotá", direccion="Bogotá, Colombia", nivel_precio="económico", num_resenas=3,
                               sector="comercio_mayorista"), offer, "diagnostico_rentabilidad")
    assert strong["total"] >= 80 and strong["clasificacion"] == "Prospecto prioritario"
    assert weak["total"] < 40
    chain = score_prospect(base(nombre="Juan Valdez Café", num_resenas=900, whatsapp="3001234567"), offer)
    assert chain["descartes"] and chain["total"] <= 30
    closed = score_prospect(base(estado_negocio="CLOSED_PERMANENTLY"), offer)
    assert "Negocio cerrado" in closed["descartes"]


def test_followers_do_not_add_points(offer):
    a = score_prospect(base(), offer)
    b = score_prospect(base(seguidores_instagram=250000, senales={"seguidores": 250000}), offer)
    assert a["total"] == b["total"]

"""Verifica el manejo de respuestas de Claude con un cliente falso (solo en pruebas)."""
import json
from types import SimpleNamespace

from prospector.agent.intel import build_brief
from prospector.agent.llm import LLM
from prospector.agent.outreach import build_messages
from prospector.agent.planner import plan_instruction
from prospector.agent.qualify import score_prospect


class FakeMessages:
    def __init__(self, payloads):
        self.payloads, self.calls = list(payloads), []

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.payloads.pop(0), ensure_ascii=False)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def fake_llm(payloads):
    llm = LLM(False, "claude-opus-5-5")
    msgs = FakeMessages(payloads)
    llm._client = SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs))
    return llm, msgs


def test_llm_plan_brief_and_messages(offer):
    llm, msgs = fake_llm([
        {"cantidad": 40, "sectores": ["restaurante", "inventado"], "ciudades": ["envigado", "Bogotá"],
         "servicio_objetivo": "control_caja", "min_sedes": 1, "palabras_clave": ["gastrobar"], "justificacion": "ok"},
        {"que_hace": "Restaurante de comida típica.", "necesidad_principal": "Flujo de caja con nómina y proveedores",
         "necesidades_potenciales": ["Flujo de caja"], "oportunidad": "Necesidad potencial por validar.",
         "servicio_recomendado": "control_caja", "argumento_comercial": "Arg.", "proximo_paso": "Escribir por WhatsApp."},
        {"whatsapp": "Hola", "correo_asunto": "Asunto", "correo_cuerpo": "Cuerpo", "linkedin": "Hola",
         "llamada": "1. Saludo", "visita": "1. Llegar", "preguntas_reunion": ["¿Cómo fijan precios?"], "propuesta_valor": "Valor"},
    ])
    plan = plan_instruction("Busca 40 restaurantes en Envigado y Bogotá para control de caja", offer, llm)
    assert plan.interpretado_por == "Claude" and plan.sectores == ["restaurante"]
    assert plan.ciudades == ["Envigado", "Bogotá"] and plan.servicio_objetivo == "control_caja"
    call = msgs.calls[0]
    assert call["fallbacks"] == "default" and call["output_config"]["format"]["type"] == "json_schema"

    p = {"nombre": "Fonda X", "sector": "restaurante", "ciudad": "Envigado", "estado_negocio": "OPERATIONAL",
         "num_sedes": 1, "num_resenas": 200, "whatsapp": "3001112233", "senales": {}}
    score = score_prospect(p, offer, "control_caja")
    brief = build_brief(p, [], offer, score, "control_caja", llm)
    assert brief["generado_por"] == "Claude" and brief["servicio_recomendado"] == "control_caja"
    msgs_out, origen = build_messages(p, brief, offer, llm)
    assert origen == "Claude" and msgs_out["correo"]["asunto"] == "Asunto"


def test_llm_prohibited_claims_fall_back_to_rules(offer):
    llm, _ = fake_llm([{"que_hace": "x", "necesidad_principal": "y", "necesidades_potenciales": [],
                        "oportunidad": "La empresa tiene problemas de caja", "servicio_recomendado": "control_caja",
                        "argumento_comercial": "z", "proximo_paso": "w"}])
    p = {"nombre": "Fonda X", "sector": "restaurante", "ciudad": "Medellín", "estado_negocio": "OPERATIONAL",
         "num_resenas": 200, "whatsapp": "3001112233", "senales": {}}
    brief = build_brief(p, [], offer, score_prospect(p, offer), "diagnostico_rentabilidad", llm)
    assert brief["generado_por"] == "reglas"

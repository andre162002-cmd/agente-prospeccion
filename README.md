# Agente de prospección comercial – Finanzas a la carta

Agente que investiga el mercado, encuentra negocios reales que encajan con la oferta de
**Finanzas a la carta** (diagnóstico de rentabilidad y finanzas para cafeterías y restaurantes
en Medellín), los califica de 0 a 100 con una explicación por criterio, los relaciona con un
servicio concreto, prepara mensajes personalizados y los gestiona en un CRM.

El agente **no inventa resultados** y **no envía mensajes**: todo envío lo aprueba y lo hace el usuario.

> **¿No eres técnico?** Sigue la [guía paso a paso](docs/GUIA_PASO_A_PASO.md): se instala con doble clic en `iniciar`.

## Qué hace

| Etapa | Módulo | Qué hace |
|---|---|---|
| Interpretar la instrucción | `agent/planner.py` | Convierte "Encuentra 50 restaurantes en Medellín…" en un plan: sectores, ciudades, servicio objetivo, filtros y consultas |
| Encontrar empresas | `sources/google_places.py` | Google Places API (New), la fuente oficial de Google Maps |
| Investigar cada empresa | `sources/website.py` | Revisa su sitio web (respetando robots.txt): correo y WhatsApp publicados, redes, formulario, responsable, señales (domicilios, vacantes, nuevas sedes, tamaño de la carta) |
| Contactos y deduplicación | `agent/runner.py`, `normalize.py` | Agrupa sedes de una misma empresa y evita duplicados por place_id, dominio, teléfono y nombre |
| Calificar | `agent/qualify.py` | Puntaje de 0 a 100 con 6 criterios ponderados y la razón de cada punto |
| Relacionar con la oferta | `agent/intel.py` | Elige UNA necesidad potencial y UN servicio, y arma la ficha comercial |
| Mensajes | `agent/outreach.py` | WhatsApp, correo, LinkedIn, guion de llamada, guion de visita, preguntas de reunión y propuesta de valor, como borradores |
| CRM | `db.py`, `web/` | Dashboard, filtros, ficha, estados comerciales, historial, duplicados, exportación a CSV y Excel |
| Cumplimiento | `compliance.py` | Lista de exclusión, frecuencia de contacto, aprobación humana y retención (Ley 1581) |

La oferta, los sectores, las ciudades y los pesos de calificación están en **`config/oferta.yaml`**.
Ese archivo es la única fuente de verdad sobre qué vendemos y a quién.

## Instalación

Requiere Python 3.11 o superior.

```bash
cd agente-prospeccion
python -m venv .venv && source .venv/bin/activate   # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # Luego edita .env con tus claves
```

### Claves (archivo `.env`, nunca en el código)

1. **Google Places API** (necesaria para buscar empresas):
   - Entra a <https://console.cloud.google.com/>, crea un proyecto y activa la facturación (Google da un crédito mensual gratuito).
   - En "APIs y servicios" habilita **Places API (New)**.
   - Crea una clave en "Credenciales" y restríngela a *Places API (New)*.
   - Pégala en `.env` como `GOOGLE_PLACES_API_KEY=...`.
2. **Anthropic (Claude)** (opcional, mejora la interpretación, las fichas y los mensajes):
   - Crea una clave en <https://console.anthropic.com/> y pégala como `ANTHROPIC_API_KEY=...`.
   - Sin esta clave, el agente funciona con reglas y plantillas propias.

## Uso

```bash
python -m prospector servidor          # Abre http://127.0.0.1:8000
```

Desde la terminal:

```bash
python -m prospector buscar "Encuentra 30 cafeterías en Envigado que puedan necesitar costeo de productos"
python -m prospector exportar --formato xlsx --salida prospectos.xlsx
python -m prospector purgar            # Aplica la política de retención
```

Flujo de trabajo recomendado:

1. **Buscar**: escribe la instrucción. El agente planifica, busca, investiga, califica y prepara borradores.
2. **Revisar la corrida**: el informe dice cuántas empresas encontró, cuántas verificó, cuántas califican y cuántas requieren más investigación.
3. **Prospectos**: filtra por puntaje, sector o ciudad. Abre la ficha de cada empresa.
4. **Mensajes**: edita, aprueba, envía tú mismo por WhatsApp, correo o Instagram, y marca el mensaje como enviado.
5. **Seguimiento**: registra respuestas y reuniones; el estado comercial avanza en el CRM.

Si no tienes la clave de Google Places, puedes **importar un CSV** (ferias, referidos, listas propias)
o **agregar empresas a mano**; el agente las investiga y califica igual.

## Pruebas

```bash
python -m pytest -q
```

Las pruebas usan respuestas HTTP de prueba (solo dentro de `tests/`) para verificar búsqueda,
deduplicación, investigación web, calificación, mensajes, cumplimiento, interfaz y exportación sin
gastar cuota.

## Documentación

- `docs/AUDITORIA.md`: auditoría de la oferta y decisiones validadas.
- `docs/ARQUITECTURA.md`: diseño, modelo de datos, fuentes, costos y limitaciones.
- `docs/CUMPLIMIENTO.md`: protección de datos y reglas de contacto.

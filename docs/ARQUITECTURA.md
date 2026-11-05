# Arquitectura y decisiones técnicas

## Principios

1. **Un solo agente con herramientas especializadas**, no varios agentes coordinados. Los ocho
   roles propuestos (mercado, descubrimiento, empresa, contacto, calificación, inteligencia,
   outreach, CRM) son módulos con una función clara. Así es más barato, predecible y fácil de
   probar. Se puede pasar a varios agentes después sin cambiar los datos.
2. **Lo determinista va en código; la IA, donde aporta**. La búsqueda, la deduplicación, la
   extracción de contactos y el puntaje son reglas auditables. Claude interpreta instrucciones
   libres, redacta la ficha comercial y escribe los mensajes. Si Claude falla o no está
   configurado, cada paso tiene una versión basada en reglas.
3. **Evidencia antes que opinión**. Cada dato se guarda en la tabla `datos` con fuente, URL,
   fecha, confianza (alta, media, baja) y verificación (confirmado, estimado, no_disponible).
   A Claude solo se le entrega esa evidencia, sin los datos de contacto.
4. **Nada se simula**. Sin fuente configurada, la corrida termina con error explícito.

| Rol pedido | Implementación |
|---|---|
| Market Research | `planner.py` + `config/oferta.yaml` (sectores, necesidades por sector) |
| Lead Discovery | `sources/google_places.py`, `sources/csv_import.py`, alta manual |
| Company Research | `sources/website.py` + datos de Google |
| Contact Research | `sources/website.py` (canales publicados, responsable con cargo) |
| Lead Qualification | `agent/qualify.py` |
| Sales Intelligence | `agent/intel.py` |
| Outreach | `agent/outreach.py` |
| CRM Manager | `db.py`, `compliance.py`, `export.py`, `web/` |

## Stack

- **Python 3.11+**, FastAPI con plantillas Jinja2 (sin paso de compilación), SQLite.
- **httpx** para HTTP, **BeautifulSoup** para leer HTML y **openpyxl** para Excel.
- **SDK de Anthropic**: modelo `claude-opus-5-5` por defecto (configurable con `CLAUDE_MODEL`).
  Salida JSON validada con esquema (`output_config.format`), esfuerzo `low` para tareas
  acotadas, y respaldo automático del servidor ante rechazos (`fallbacks: "default"`).
  Si la plataforma no admite ese respaldo, se reintenta sin él.

SQLite basta para un consultor independiente (miles de prospectos). Para un equipo, basta
cambiar `db.py` por PostgreSQL; el resto del código no cambia.

## Modelo de datos

- `prospectos`: un registro por empresa (no por sede). Incluye los campos pedidos: ID, nombre,
  sector, ciudad, web, redes, contacto, cargo, correo, teléfono, servicio, problema potencial,
  justificación, puntaje, clasificación, estado comercial, fechas y observaciones. Además guarda
  señales, el detalle del puntaje y la ficha (JSON).
- `sedes`: lugares de Google agrupados bajo una empresa (para el conteo de sedes).
- `datos`: evidencia con procedencia (ver principio 3).
- `historial`: bitácora de investigación y gestión por prospecto.
- `corridas`: instrucción, plan, bitácora e informe de cada ejecución.
- `mensajes`: borradores por canal y su estado (borrador, aprobado, enviado, descartado).
- `contactos`: registro de cada contacto realizado.
- `exclusiones`: lista de no contactar.

## Deduplicación

Al ingresar un lugar se busca, en este orden: el mismo `place_id` (propio o de una sede), el
mismo dominio web, el mismo teléfono y el mismo nombre normalizado (sin tildes, sin S.A.S. ni
"Sede X"). Si coincide un lugar distinto, se agrega como **sede**. Los nombres parecidos pero
no idénticos aparecen en `/duplicados` para que el usuario decida si fusionarlos.

## Calificación (0–100)

Los pesos por defecto son 25/25/15/15/10/10 y cambian por servicio objetivo en
`calificacion.pesos_por_servicio`. Cada criterio da un factor entre 0 y 1 y una lista de razones:

- **Cliente ideal**: prioridad del sector; independiente o cadena (lista de exclusión y máximo
  de sedes); en operación según Google; reseñas como señal de operación estable (estimado).
- **Necesidad**: sector; ventas por domicilios; varias sedes; tamaño de la carta publicada;
  volumen de clientes; expansión. Se reduce si el servicio objetivo no aplica al sector.
- **Capacidad**: nivel de precios en Google, número de sedes, volumen de clientes y sitio propio.
- **Accesibilidad**: WhatsApp, celular, correo, formulario, Instagram y responsable identificado.
- **Crecimiento**: varias sedes, nuevas sedes, vacantes y diversificación de canales.
- **Geografía**: puntaje por ciudad desde la configuración.

Seguidores y likes no suman nada. Las cadenas, franquicias grandes y negocios cerrados quedan
en máximo 30 puntos y se descartan.

## Costos aproximados

- **Google Places**: cada consulta devuelve hasta 20 lugares. Una corrida de 50 empresas usa
  unas 5 a 15 solicitudes, porque busca más resultados de los necesarios para compensar
  duplicados y descartes. Los campos pedidos (contacto, nivel de precios, domicilios) entran en
  las categorías de facturación más altas de Text Search; revisa la tabla vigente en
  <https://developers.google.com/maps/billing-and-pricing/pricing>. Google da un crédito
  mensual que suele cubrir el uso de un consultor.
- **Claude**: hasta 2 llamadas por empresa calificada (ficha y mensajes) más 1 por corrida
  (plan). El informe de cada corrida muestra las llamadas y los tokens usados. Para bajar
  costos, usa `CLAUDE_EFFORT=low` o desactiva la IA (`PROSPECTOR_USAR_IA=0`).

## Limitaciones conocidas

- **LinkedIn, Instagram y Facebook** no permiten extraer datos de perfiles sin una integración
  aprobada. El agente registra los enlaces que publica el propio negocio, pero no lee esos perfiles.
- **Cámara de Comercio y RUES**: no se consultan automáticamente (sin API pública para este uso).
  La razón social y la antigüedad se completan a mano en la ficha.
- **Responsables**: solo se detectan si el sitio web los publica con cargo ("Fundadora: …").
  Casi siempre el contacto será un canal del negocio.
- **Tamaño, capacidad y antigüedad** son estimaciones a partir de señales públicas.
- **Dos negocios distintos con el mismo nombre** en el área metropolitana se agrupan como sedes.
  Revisa la lista de sedes en la ficha; si una no corresponde, elimina ese prospecto y registra cada negocio a mano. Separar registros desde la interfaz queda pendiente.
- **Sitios hechos solo con JavaScript** pueden mostrar poco contenido al lector HTML.
- **No se pudo probar contra servicios reales** en el entorno de desarrollo, porque la red
  estaba restringida. La primera corrida real debe revisarse con atención (ver README).

## Etapa 7 – Optimización (siguientes pasos sugeridos)

- Medir, después de las primeras 100 empresas, qué criterios predicen respuestas reales y ajustar los pesos.
- Enviar las fichas en lote con la API de Batches de Anthropic (50 % más barato) cuando las corridas sean grandes.
- Guardar en caché las consultas de Places para no repetirlas en 30 días.
- Integrar WhatsApp Business Cloud API solo para registrar respuestas, siempre con envío manual.

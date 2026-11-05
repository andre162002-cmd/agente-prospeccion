# Protección de datos y reglas de contacto

Marco: Ley 1581 de 2012 y Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015), más los
términos de uso de cada plataforma. Este documento describe controles técnicos y no es asesoría
legal. Antes de escalar campañas, conviene validar la política de tratamiento de datos con un abogado.

| Principio | Cómo lo aplica el sistema |
|---|---|
| Finalidad | Prospección B2B de servicios de análisis financiero. La finalidad está en `config/oferta.yaml` y en la página de Cumplimiento. |
| Minimización | Solo datos del establecimiento: nombre comercial, dirección y canales que publica el propio negocio. No se guardan datos sensibles. A Claude no se le envían datos de contacto. |
| Veracidad y procedencia | Cada dato guarda fuente, URL, fecha, confianza y verificación. Nunca se deducen correos (como nombre.apellido@) ni se inventan nombres o teléfonos. |
| Acceso y circulación restringida | Base de datos local; claves en `.env`, que está excluido de git. |
| Personas naturales | El nombre y el cargo de un responsable solo se guardan si el negocio los publica con su cargo, con la URL de la fuente. Los correos de dominio gratuito se marcan con confianza "media" porque podrían ser personales. |
| No contactar | "Agregar a lista de exclusión" bloquea teléfono, WhatsApp, correo, dominio, place_id y nombre, borra los borradores y evita que la empresa se vuelva a registrar. |
| Supresión | "Eliminar datos" borra el prospecto y toda su información. |
| Frecuencia | Mínimo 7 días entre contactos y máximo 3 intentos sin respuesta (configurable). |
| Aprobación humana | Ningún mensaje se envía automáticamente. El flujo es borrador → aprobado (valida reglas) → enviado por el usuario → registro. |
| Retención | Descartados: 180 días. Nunca contactados: 365 días sin actividad. Se aplica con el botón de Cumplimiento o con `python -m prospector purgar`. |
| Plataformas | Google Places API oficial; sitios web propios respetando robots.txt, con User-Agent identificado y pausas entre páginas; sin CAPTCHAs, inicios de sesión ni scraping de Instagram, Facebook o LinkedIn. |

Los correos comerciales incluyen una línea para pedir no ser contactado. Cuando alguien lo pida
por cualquier canal, regístralo de inmediato con "Agregar a lista de exclusión".

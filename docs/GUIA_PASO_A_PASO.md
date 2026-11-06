# Guía paso a paso (sin conocimientos técnicos)

Esta guía es para Windows. Si usas Mac, mira el final.
Solo necesitas hacer las partes 1 a 4 una vez. Después, para usar el agente, basta la parte 5.

---

## Parte 1. Instalar Python (una sola vez, unos 5 minutos)

Python es el programa que hace funcionar el agente. Es gratuito.

1. Entra a <https://www.python.org/downloads/>. Usa **Python 3.13**: las versiones más nuevas (3.14, 3.15) todavía no
   funcionan con todos los componentes. Si ya instalaste otra versión, no pasa nada: el archivo `iniciar`
   instala la 3.13 por su cuenta.
2. Haz clic en el botón amarillo grande **"Download Python"**.
3. Abre el archivo que se descargó (está en tu carpeta **Descargas**).
4. **Muy importante:** en la primera ventana del instalador, abajo, marca la casilla
   **"Add python.exe to PATH"**.
5. Haz clic en **"Install Now"** y espera a que termine. Luego haz clic en **"Close"**.

## Parte 2. Descargar el agente (una sola vez)

1. Entra a <https://github.com/andre162002-cmd/agente-prospeccion> con tu cuenta de GitHub abierta.
2. Haz clic en el botón verde **"<> Code"** y luego en **"Download ZIP"**.
3. Ve a tu carpeta **Descargas**, haz clic derecho sobre `agente-prospeccion-main.zip` y
   elige **"Extraer todo…"**, luego **"Extraer"**.
4. Te queda una carpeta llamada `agente-prospeccion-main`. Muévela a un lugar fácil de
   encontrar, por ejemplo a **Documentos**.

## Parte 3. Conseguir la clave de Google (una sola vez, unos 15 minutos)

La clave es como una contraseña que le permite al agente buscar negocios en Google Maps.
Google pide una tarjeta para activar la cuenta, pero da un crédito mensual gratuito que
normalmente cubre este uso. No te cobra nada sin que lo veas en tu cuenta.

1. Entra a <https://console.cloud.google.com/> con tu cuenta de Gmail y acepta los términos.
2. Arriba, junto al logo de Google Cloud, haz clic en **"Seleccionar un proyecto"**, luego
   **"Proyecto nuevo"**. Ponle de nombre `agente-prospeccion` y haz clic en **"Crear"**.
3. Activa la facturación: en el buscador de arriba escribe **"Facturación"**, entra y sigue
   los pasos para agregar tu tarjeta y vincularla al proyecto.
4. En el buscador de arriba escribe **"Places API (New)"**, ábrela y haz clic en **"Habilitar"**.
5. En el buscador escribe **"Credenciales"** y entra. Haz clic en **"+ Crear credenciales"** y
   luego en **"Clave de API"**.
6. Aparece una clave larga (empieza por `AIza…`). Haz clic en el ícono de copiar y pégala por
   ahora en un lugar seguro (por ejemplo, un correo a ti mismo).
7. Recomendado: haz clic en **"Editar clave de API"**, en "Restricciones de API" elige
   **"Restringir clave"**, marca **"Places API (New)"** y guarda. Así la clave solo sirve para esto.
8. Opcional, para no llevarte sorpresas: en el buscador escribe **"Presupuestos y alertas"** y
   crea un presupuesto de, por ejemplo, 10 dólares con aviso por correo.

> La clave es privada: no la publiques ni la compartas.

## Parte 4. Encender el agente por primera vez

1. Abre la carpeta `agente-prospeccion-main`.
2. Haz doble clic en el archivo **`iniciar`** (o `iniciar.bat`).
   - Si Windows muestra **"Windows protegió su PC"**, haz clic en **"Más información"** y
     luego en **"Ejecutar de todas formas"**.
3. Se abre una ventana negra. La primera vez tarda unos minutos preparando todo.
4. Después se abre el **Bloc de notas** con un archivo de configuración. Busca la línea:
   ```
   GOOGLE_PLACES_API_KEY=
   ```
   y pega tu clave justo después del signo `=`, sin espacios. Debe quedar así:
   ```
   GOOGLE_PLACES_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXX
   ```
5. Guarda con **Ctrl + G** (o **Ctrl + S**) y cierra el Bloc de notas.
6. A los pocos segundos se abre tu navegador con el agente. Si no se abre solo, escribe en el
   navegador: `127.0.0.1:8000`.

> **No cierres la ventana negra** mientras uses el agente. Cuando termines, ciérrala y el agente se apaga.

## Parte 5. Usar el agente (cada vez)

1. Doble clic en **`iniciar`** dentro de la carpeta. Espera a que se abra el navegador.
2. **Primera prueba (pequeña):** haz clic en **"Buscar"** en el menú de arriba y escribe:
   > Encuentra 10 cafeterías en Laureles, Medellín que puedan necesitar costeo de productos
3. Haz clic en **"Planificar y ejecutar"**. Verás el avance; tarda unos minutos.
4. Al terminar verás el informe: cuántas empresas encontró, cuántas califican y cuántas
   necesitan más investigación.
5. Haz clic en **"Prospectos"** para ver la lista ordenada por puntaje. Abre cualquier empresa
   para ver su **ficha**: por qué tiene ese puntaje, qué servicio ofrecerle y los mensajes listos.
6. **Mensajes:** revisa y corrige el texto, haz clic en **"Aprobar"**, cópialo y envíalo tú
   mismo por WhatsApp. Luego vuelve y haz clic en **"Marcar como enviado"**.
7. **Excel:** en **"Prospectos"**, el botón **"Exportar Excel"** descarga toda la lista.

Tus datos se guardan en tu computador (carpeta `data`) y siguen ahí la próxima vez que abras el agente.

## Opcional: activar la inteligencia artificial

Sin esta clave el agente funciona con plantillas. Con ella, las fichas y los mensajes quedan
más personalizados. Tiene un costo por uso, normalmente de unos centavos de dólar por empresa.

1. Entra a <https://console.anthropic.com/>, crea una cuenta y agrega saldo en **"Billing"**.
2. Ve a **"API Keys"** y haz clic en **"Create Key"**. Copia la clave (empieza por `sk-ant-…`).
3. En la carpeta del agente, haz clic derecho en el archivo **`.env`**, elige **"Abrir con"** y
   luego **"Bloc de notas"**. Pega la clave después de `ANTHROPIC_API_KEY=`, guarda y cierra.
4. Cierra la ventana negra y vuelve a abrir **`iniciar`**.

## Problemas comunes

| Lo que ves | Qué hacer |
|---|---|
| "No encuentro Python" | Repite la Parte 1 y no olvides marcar **"Add python.exe to PATH"**. Si ya lo instalaste, reinicia el computador. |
| La corrida dice "falta GOOGLE_PLACES_API_KEY" | Abre `.env` con el Bloc de notas y revisa que la clave esté pegada después del `=`. Cierra la ventana negra y abre `iniciar` de nuevo. |
| "Google Places respondió 403" | La clave no es válida, la "Places API (New)" no está habilitada o falta la facturación. Revisa la Parte 3. |
| No veo el archivo `.env` | Ese archivo solo aparece después de abrir `iniciar` por primera vez. En la carpeta puede verse sin nombre, solo como tipo "Archivo ENV". |
| El navegador dice "no se puede acceder" | Espera unos segundos y recarga la página. Revisa que la ventana negra siga abierta. |

## Si usas Mac

Igual que en Windows, con estas diferencias:
- En la Parte 1, el instalador de python.org no tiene la casilla del PATH; solo instálalo.
- En la Parte 4, haz clic derecho sobre **`iniciar.command`** y elige **"Abrir"**; confirma
  **"Abrir"** en el aviso. La clave se pega en el archivo que se abre en TextEdit.

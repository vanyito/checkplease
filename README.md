# Check Please! — Backend Flask (Fase 1 + 2 + 3 + 4)

Divide la cuenta, no la amistad. 🤚

- **Fase 1:** app Flask con detección de idioma por IP (`/api/geo`) y tasas
  de cambio en vivo (`/api/rates`).
- **Fase 2:** persistencia con SQLite — compartir cuentas por link
  (`/s/<share_id>`) e historial por cookie de visitante (`/api/bills`,
  `/api/history`).
- **Fase 3:** escaneo de boletas con OCR local (Tesseract) —
  `/api/scan-receipt`. Ver la sección [OCR](#-ocr-escanear-boletas) más abajo,
  requiere instalar un programa aparte del proyecto.
- **Fase 4:** deploy a internet. El código ya está listo (PostgreSQL en
  producción, Gunicorn, puerto dinámico — ver [Deploy](#-deploy-a-producción-render)
  más abajo), pero los pasos de cuenta/dominio todavía los tienes que hacer
  tú a mano siguiendo la guía de esa sección.
- **Edición colaborativa:** el link para compartir se puede generar desde
  el principio (botón "Compartir cuenta"), antes de terminar de repartir.
  Mientras la cuenta no esté finalizada, cualquiera que abra ese link puede
  seguir agregando gente e ítems — ver la sección
  [Edición colaborativa](#-edición-colaborativa) más abajo.

Todavía **no** hay cuentas de usuario reales ni pagos — se decidió posponerlo
hasta que el experimento muestre tracción.

---

## 📁 Estructura del proyecto

```
checkplease-flask/
├── app.py              ← el servidor (el "cerebro")
├── requirements.txt    ← lista de dependencias
├── templates/
│   └── index.html      ← la app completa (lo que ve el usuario)
└── static/
    ├── css/            ← (vacío por ahora, el CSS va dentro del HTML)
    ├── js/             ← (vacío por ahora, el JS va dentro del HTML)
    └── img/
        └── logo-original.png   ← tu logo de Affinity
```

---

## 🚀 Cómo correrlo en tu computador (paso a paso)

### 1. Instala Python
Si no lo tienes, descárgalo de https://python.org (versión 3.10 o superior).
Para verificar que está instalado, abre una terminal y escribe:
```bash
python3 --version
```

### 2. Entra a la carpeta del proyecto
```bash
cd checkplease-flask
```

### 3. (Recomendado) Crea un "entorno virtual"
Un entorno virtual es una cajita aislada para las dependencias de este
proyecto, para que no se mezclen con otros. Créalo y actívalo:

```bash
# Crear el entorno (solo la primera vez)
python3 -m venv venv

# Activarlo (cada vez que trabajes en el proyecto)
# En Mac/Linux:
source venv/bin/activate
# En Windows:
venv\Scripts\activate
```

Sabrás que está activo porque verás `(venv)` al inicio de la línea.

### 4. Instala las dependencias
```bash
pip install -r requirements.txt
```

### 5. Arranca el servidor
```bash
python3 app.py
```

Verás algo como:
```
 * Running on http://127.0.0.1:5000
```

### 6. Abre la app
Abre tu navegador y entra a:
```
http://localhost:5000
```

¡Listo! La app está corriendo. Para detenerla, presiona `Ctrl + C` en la
terminal.

---

## 🧠 Cómo funciona (explicación simple)

### `app.py` — el servidor
Es un programa que "escucha" peticiones y responde. Tiene tres "rutas":

- **`/`** → cuando alguien entra a la web, le entrega el `index.html`.
- **`/api/geo`** → mira la IP del visitante, averigua de qué país es, y
  responde con el idioma y moneda sugeridos.
- **`/api/rates`** → trae las tasas de cambio actuales de una API gratuita
  (Frankfurter) y las guarda 1 hora en memoria para no pedirlas todo el rato.

### `templates/index.html` — la app
Es el prototipo que ya conocías, con un cambio importante: ahora, al cargar,
le pregunta al servidor por el idioma (`/api/geo`) y las tasas (`/api/rates`)
en vez de usar datos inventados.

---

## 🧾 OCR: escanear boletas

El botón **"Escanear"** de la app sube una foto de una boleta y la procesa
con [Tesseract](https://github.com/tesseract-ocr/tesseract), un motor de OCR
gratuito y local (no se manda la imagen a ningún servicio externo).

**Importante:** `pip install -r requirements.txt` instala el paquete de
Python `pytesseract`, pero eso es solo un "control remoto" — hace falta
instalar el **programa** Tesseract por separado en el sistema operativo.
Si no está instalado, `/api/scan-receipt` responde con un error claro en
vez de romperse.

### Instalar el binario de Tesseract

**Mac:**
```bash
brew install tesseract tesseract-lang
```
(`tesseract-lang` trae todos los paquetes de idioma, incluido español.)

**Linux (Debian/Ubuntu):**
```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

**Windows:**
1. Descarga el instalador oficial (mantenido por UB-Mannheim) desde
   https://github.com/UB-Mannheim/tesseract/wiki
2. Durante la instalación, en "Additional language data" marca al menos
   **Spanish**, además del inglés que viene por defecto.
3. Verifica en una terminal: `tesseract --version`

Si instalaste con winget (`winget install UB-Mannheim.TesseractOCR`) o no
tienes permisos de administrador para agregar el paquete de español al
tessdata del sistema, este proyecto trae una alternativa: si existe una
carpeta `tessdata/` junto a `app.py` (con `eng.traineddata` y
`spa.traineddata` adentro), `ocr.py` la usa automáticamente en vez de la
del sistema — no requiere privilegios de administrador. Puedes descargar
esos archivos desde https://github.com/tesseract-ocr/tessdata.

### Verificar la instalación
```bash
tesseract --version
tesseract --list-langs
```
Debe listar al menos `eng` y `spa`.

---

## 🤝 Edición colaborativa

El botón **"Compartir cuenta"** (visible desde el principio, no hace falta
llegar al resumen) crea el link `/s/<share_id>` de inmediato, aunque la
cuenta esté vacía o a medio armar. Cualquiera que abra ese link:

- Ve la misma lista de personas e ítems que ya existe.
- Puede seguir agregando gente, ítems, o repartir porciones — cada cambio
  se autoguarda solo en el servidor.
- **No hay sincronización en vivo.** Si dos personas tienen la página
  abierta al mismo tiempo, cada una ve sus propios cambios de inmediato,
  pero para ver lo que agregó la otra persona hay que recargar la página.
  Si ambas guardan casi al mismo tiempo sin haber recargado antes, gana el
  último guardado (se puede perder el cambio del otro) — es una limitación
  conocida, aceptable para el tamaño de este proyecto por ahora.

Cuando alguien le da a **"Terminar y compartir resultado"** (dentro del
resumen), la cuenta queda marcada como finalizada: a partir de ahí, ese
mismo link `/s/<share_id>` siempre muestra el resumen de solo lectura
(quién paga qué, con la propina aplicada) y ya no admite más ediciones.

Un link finalizado no se puede reabrir para seguir editando — hay que
crear una cuenta nueva si hace falta agregar algo después.

El botón **"QR"** genera un código QR real (`/api/qr`, con la librería
`qrcode`) del mismo link — útil para compartirlo en persona sin escribir
la URL. Apunta al mismo `share_id` que el botón "Link"; no crea una
cuenta distinta.

---

## 🚀 Deploy a producción (Render)

### Base de datos: SQLite local, PostgreSQL en producción
El disco de Render es efímero — un archivo SQLite se perdería en cada
redeploy. Por eso `db.py` cambia de motor automáticamente según exista o
no la variable de entorno `DATABASE_URL`:

- **Sin `DATABASE_URL`** (tu computador) → sigue usando SQLite, igual que
  siempre. No necesitas instalar nada nuevo para seguir desarrollando local.
- **Con `DATABASE_URL`** (Render la provee sola al conectar una base de
  datos PostgreSQL al servicio) → usa PostgreSQL automáticamente.

### Variables de entorno que usa la app
| Variable       | Dónde se usa                        | En Render                          |
|----------------|--------------------------------------|-------------------------------------|
| `DATABASE_URL` | `db.py` — elige SQLite o PostgreSQL  | La pone Render al conectar la BD    |
| `PORT`         | `app.py` — puerto del servidor       | La pone Render automáticamente      |
| `FLASK_DEBUG`  | `app.py` — apaga el modo debug       | No definirla (por defecto queda apagada en Gunicorn) |

Ninguna de estas hace falta configurarla a mano salvo `DATABASE_URL`, que
Render completa sola.

### Pasos para desplegar
1. **GitHub:** este proyecto tiene que vivir en un repositorio de GitHub
   para que Render lo pueda desplegar. Si no es todavía un repo git:
   ```bash
   git init
   git add .
   git commit -m "Check Please! — listo para deploy"
   ```
   Luego crea un repositorio en GitHub (privado o público, tu elección) y
   conéctalo:
   ```bash
   git remote add origin <URL-de-tu-repo>
   git branch -M main
   git push -u origin main
   ```
2. **Crear la base de datos en Render:** New → PostgreSQL → plan gratuito.
   Copia la "Internal Database URL" que te entrega.
3. **Crear el Web Service en Render:** New → Web Service → conecta el repo.
   - Root Directory: **vacío** (déjalo en blanco — `app.py` está en la raíz
     del repo, no en una subcarpeta).
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Plan: Free
4. **Variables de entorno del Web Service:** agrega `DATABASE_URL` con el
   valor copiado en el paso 2.
5. Verifica la URL `.onrender.com` que Render asigna: la home, `/api/geo`,
   `/api/rates`, compartir una cuenta y abrir su link, el historial.

**Nota:** en el plan gratuito, Render duerme el servicio tras 15 minutos sin
tráfico — la siguiente visita tarda ~30-60 segundos en responder mientras
despierta. Es esperable, no es un bug. La base PostgreSQL gratuita también
expira (Render mostró 30 días al crearla) — se puede recrear cuando toque.

### ⚠️ Escaneo de boletas (OCR): pendiente en producción
El entorno nativo de Python en el plan gratuito de Render **no permite
`apt-get`** durante el build (sistema de archivos de solo lectura), así que
no se pudo instalar el binario de Tesseract ahí. `/api/scan-receipt`
responde `success: false` con un mensaje claro en vez de romperse — el
resto de la app (compartir, historial, conversor) funciona normal.

Queda [`render-build.sh`](render-build.sh) en el repo, sin usar por ahora,
como referencia de qué instalar. Para que el OCR funcione en producción
hace falta migrar el Web Service a un deploy con **Docker** (ahí sí se
puede correr `apt-get install tesseract-ocr` con permisos de root durante
la construcción de la imagen) — pendiente para una iteración futura.

### Dominio propio
Una vez que la URL de Render funcione bien, en el dashboard del Web Service
→ Settings → Custom Domains, agrega tu dominio y configura en tu registrador
(Namecheap, Porkbun, etc.) el registro DNS que Render te indique. El
certificado HTTPS lo genera Render automáticamente, sin configuración
adicional.

---

## 🔒 Nota sobre "localhost"

Cuando corres la app en tu propio computador, la IP es `127.0.0.1` (local),
que no se puede geolocalizar. Por eso en desarrollo el idioma cae a inglés por
defecto. Cuando subamos la app a internet (hosting real), detectará el país de
verdad.

Puedes forzar un idioma manualmente con el selector 🌐 de arriba.

---

## ⏭️ Qué falta

- **App en internet:** ✅ ya está desplegada en Render y verificada
  (home, `/api/geo`, `/api/rates`, compartir, historial funcionando en
  producción con PostgreSQL real).
- **OCR en producción:** pendiente — ver la nota de arriba sobre Docker.
- **Dominio propio:** falta comprarlo y conectarlo (ver sección
  [Deploy](#-deploy-a-producción-render)) — paso que hace el humano.
- **Más adelante (sin fecha):** cuando haya tráfico real, activar Google
  AdSense. Cuando valga la pena monetizar, retomar login y plan Pro con
  pagos — pausado deliberadamente por ahora.

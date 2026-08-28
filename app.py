"""
Check Please! — Flask backend (Fase 1 + Fase 2 + Fase 3 + edición colaborativa)
================================================================================
Sirve la aplicación y expone los endpoints:
  - /api/geo               -> detecta el idioma según la IP de quien visita
  - /api/rates             -> tasas de cambio en vivo (con caché)
  - /api/bills             -> crea una cuenta y devuelve su link para compartir
  - /api/bills/<id>        -> [PUT] autoguardado mientras se edita entre varios
  - /api/bills/<id>/finalize -> [POST] cierra la edición, el link pasa a solo lectura
  - /s/<id>                -> si no está finalizada: app editable con el estado
                               actual (cualquiera con el link puede seguir
                               agregando cosas). Si ya está finalizada: resumen
                               de solo lectura.
  - /api/history           -> lista las cuentas creadas por este visitante
  - /api/scan-receipt      -> OCR de una foto de boleta con Tesseract (Fase 3)

Persistencia con SQLite en desarrollo / PostgreSQL en producción (ver
db.py), identificando al visitante con una cookie anónima (cp_visitor)
sin necesidad de login — eso vendrá recién en una fase futura. El
escaneo de boletas usa OCR local (ver ocr.py) — requiere el binario de
Tesseract instalado en el sistema (ver README).
"""

import os
import time
import urllib.request
import json
import uuid
from flask import Flask, render_template, jsonify, request, g

import db
import ocr

app = Flask(__name__)

# Crea la tabla `bills` si no existe todavía (no borra datos existentes).
db.init_db()

# Nombre y duración de la cookie de visitante anónimo.
VISITOR_COOKIE_NAME = "cp_visitor"
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 año en segundos

# ──────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ──────────────────────────────────────────────────────────

# Idiomas que soportamos. Si el país detectado no está en el mapa,
# caemos a inglés por defecto.
SUPPORTED_LANGS = {"es", "en", "pt", "fr"}

# Mapa país -> idioma. Solo unos cuantos; se puede ampliar.
COUNTRY_TO_LANG = {
    "CL": "es", "AR": "es", "ES": "es", "MX": "es", "CO": "es",
    "PE": "es", "UY": "es", "VE": "es", "EC": "es", "BO": "es",
    "BR": "pt", "PT": "pt",
    "FR": "fr", "BE": "fr",
    "US": "en", "GB": "en", "AU": "en", "CA": "en",
}

# Moneda por país (para precargar el conversor y el símbolo)
COUNTRY_TO_CURRENCY = {
    "CL": "CLP", "AR": "ARS", "ES": "EUR", "MX": "MXN", "CO": "COP",
    "PE": "PEN", "BR": "BRL", "PT": "EUR", "FR": "EUR", "US": "USD",
    "GB": "GBP", "CA": "CAD", "AU": "AUD",
}


# ──────────────────────────────────────────────────────────
#  RUTA PRINCIPAL: sirve la app
# ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Sirve la página principal (la app de una sola página), vacía."""
    return render_template("index.html", initial_bill=None)


# ──────────────────────────────────────────────────────────
#  ENDPOINT: /api/geo  — detección de idioma por IP
# ──────────────────────────────────────────────────────────

def get_client_ip():
    """
    Obtiene la IP real del visitante.
    Cuando la app está detrás de un proxy (como en Render/Railway),
    la IP real viene en la cabecera 'X-Forwarded-For'.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Puede venir una lista "ip_real, proxy1, proxy2" -> tomamos la primera
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


@app.route("/api/geo")
def api_geo():
    """
    Detecta el país del visitante por su IP y devuelve el idioma
    y la moneda sugeridos. El frontend usa esto para precargar todo.
    """
    ip = get_client_ip()

    # Valores por defecto si no logramos detectar
    country = None
    lang = "en"
    currency = "USD"

    # IPs locales (desarrollo) no se pueden geolocalizar
    is_local = ip.startswith(("127.", "192.168.", "10.", "172.")) or ip in ("", "::1")

    if not is_local:
        try:
            # ip-api.com: gratis, sin API key, hasta 45 req/min
            url = f"http://ip-api.com/json/{ip}?fields=status,countryCode"
            with urllib.request.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "success":
                    country = data.get("countryCode")
                    lang = COUNTRY_TO_LANG.get(country, "en")
                    currency = COUNTRY_TO_CURRENCY.get(country, "USD")
        except Exception as e:
            # Si falla la geolocalización, seguimos con los defaults
            app.logger.warning(f"Geo lookup failed: {e}")

    return jsonify({
        "ip": ip,
        "country": country,
        "lang": lang,
        "currency": currency,
        "is_local": is_local,
    })


# ──────────────────────────────────────────────────────────
#  ENDPOINT: /api/rates  — tasas de cambio en vivo (con caché)
# ──────────────────────────────────────────────────────────

# Guardamos las tasas en memoria para no llamar a la API en cada request.
# _rates_cache = {"data": {...}, "fetched_at": timestamp}
_rates_cache = {"data": None, "fetched_at": 0}
RATES_TTL = 60 * 60  # 1 hora en segundos


@app.route("/api/rates")
def api_rates():
    """
    Devuelve las tasas de cambio con base USD.
    Usa Frankfurter (open source, sin API key). Cachea 1 hora.
    """
    now = time.time()

    # Si el caché sigue fresco, lo devolvemos sin llamar a la API
    if _rates_cache["data"] and (now - _rates_cache["fetched_at"] < RATES_TTL):
        return jsonify({
            "base": "USD",
            "rates": _rates_cache["data"],
            "cached": True,
        })

    # Monedas que nos interesan
    symbols = "EUR,GBP,CLP,MXN,ARS,BRL,COP,PEN,JPY,CAD,AUD,CHF,CNY,INR"

    try:
        url = f"https://api.frankfurter.app/latest?from=USD&to={symbols}"
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            rates = data.get("rates", {})
            rates["USD"] = 1.0  # incluimos la base
            _rates_cache["data"] = rates
            _rates_cache["fetched_at"] = now
            return jsonify({"base": "USD", "rates": rates, "cached": False})
    except Exception as e:
        app.logger.warning(f"Rates fetch failed: {e}")
        # Fallback: tasas aproximadas si la API falla
        fallback = {
            "USD": 1, "EUR": 0.92, "GBP": 0.79, "CLP": 950, "MXN": 17.1,
            "ARS": 900, "BRL": 5.0, "COP": 3900, "PEN": 3.75, "JPY": 149,
            "CAD": 1.36, "AUD": 1.53, "CHF": 0.90, "CNY": 7.24, "INR": 83.1,
        }
        return jsonify({"base": "USD", "rates": fallback, "cached": False, "fallback": True})


# ──────────────────────────────────────────────────────────
#  COOKIE DE VISITANTE ANÓNIMO
# ──────────────────────────────────────────────────────────
# Sin login todavía (eso es Fase 4), identificamos a cada visitante
# con un UUID guardado en una cookie. Si no la trae, se la creamos.

@app.before_request
def load_visitor_id():
    """Lee la cookie cp_visitor; si no existe, prepara una nueva."""
    visitor_id = request.cookies.get(VISITOR_COOKIE_NAME)
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
        g.new_visitor_id = visitor_id  # se setea como cookie en after_request
    g.visitor_id = visitor_id


@app.after_request
def set_visitor_cookie(response):
    """Si el visitante no traía cookie, se la asignamos en la respuesta."""
    new_id = getattr(g, "new_visitor_id", None)
    if new_id:
        response.set_cookie(
            VISITOR_COOKIE_NAME,
            new_id,
            max_age=VISITOR_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
        )
    return response


# ──────────────────────────────────────────────────────────
#  ENDPOINT: POST /api/bills — guardar una cuenta y obtener su link
# ──────────────────────────────────────────────────────────

@app.route("/api/bills", methods=["POST"])
def api_create_bill():
    """
    Recibe el estado de la cuenta ya repartida (people, items,
    assignments, totals...) y lo guarda como una fila nueva en `bills`.
    Devuelve el share_id y la URL para compartir.
    """
    data = request.get_json(silent=True) or {}

    payload = data.get("payload")
    if not isinstance(payload, dict):
        return jsonify({"error": "payload es requerido"}), 400

    title = (data.get("title") or "").strip()[:120]  # límite defensivo
    currency = data.get("currency") or "USD"
    lang = data.get("lang") or "es"
    try:
        tip_pct = float(data.get("tip_pct") or 0)
    except (TypeError, ValueError):
        tip_pct = 0

    share_id = db.create_bill(
        visitor_id=g.visitor_id,
        title=title,
        currency=currency,
        lang=lang,
        tip_pct=tip_pct,
        payload_dict=payload,
    )

    return jsonify({"share_id": share_id, "url": f"/s/{share_id}"})


# ──────────────────────────────────────────────────────────
#  ENDPOINT: PUT /api/bills/<share_id> — autoguardado colaborativo
# ──────────────────────────────────────────────────────────

@app.route("/api/bills/<share_id>", methods=["PUT"])
def api_update_bill(share_id):
    """
    Actualiza una cuenta ya compartida (autoguardado mientras se arma
    entre varias personas — cualquiera con el link puede editar).
    Si la cuenta ya fue finalizada, rechaza el cambio: el link pasó a
    ser de solo lectura y no debería seguir recibiendo ediciones.
    """
    data = request.get_json(silent=True) or {}

    payload = data.get("payload")
    if not isinstance(payload, dict):
        return jsonify({"error": "payload es requerido"}), 400

    title = (data.get("title") or "").strip()[:120]
    currency = data.get("currency") or "USD"
    lang = data.get("lang") or "es"
    try:
        tip_pct = float(data.get("tip_pct") or 0)
    except (TypeError, ValueError):
        tip_pct = 0

    saved = db.update_bill(share_id, title, currency, lang, tip_pct, payload)
    if not saved:
        return jsonify({"error": "Esta cuenta no existe o ya fue finalizada."}), 409

    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────
#  ENDPOINT: POST /api/bills/<share_id>/finalize — cerrar la edición
# ──────────────────────────────────────────────────────────

@app.route("/api/bills/<share_id>/finalize", methods=["POST"])
def api_finalize_bill(share_id):
    """
    Marca la cuenta como terminada. A partir de ahora su link (/s/<id>)
    muestra el resumen de solo lectura en vez de la app editable.
    """
    ok = db.finalize_bill(share_id)
    if not ok:
        return jsonify({"error": "Esta cuenta no existe."}), 404
    return jsonify({"ok": True, "url": f"/s/{share_id}"})


# ──────────────────────────────────────────────────────────
#  ENDPOINT: GET /s/<share_id> — abrir una cuenta compartida
# ──────────────────────────────────────────────────────────
# Mientras la cuenta no esté finalizada, este link abre la app editable
# precargada con lo que ya hay guardado (edición colaborativa: cualquiera
# con el link puede seguir agregando gente/ítems). Una vez finalizada,
# el mismo link muestra el resumen de solo lectura de siempre.

# El símbolo se guarda a partir del código de moneda para no repetir
# el mapeo del frontend (CURRENCY) en el backend.
CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "CLP": "$", "MXN": "$",
    "ARS": "$", "BRL": "R$", "COP": "$", "PEN": "S/", "JPY": "¥",
    "CAD": "$", "AUD": "$", "CHF": "Fr", "CNY": "¥", "INR": "₹",
}


@app.route("/s/<share_id>")
def view_shared_bill(share_id):
    bill = db.get_bill_by_share_id(share_id)
    if not bill:
        return render_template("shared_not_found.html"), 404

    if not bill["finalized"]:
        return render_template("index.html", initial_bill=bill)

    # El total base (sin propina) sale de los montos ya calculados por
    # el frontend al momento de compartir (payload["totals"]).
    totals = bill["payload"].get("totals", {})
    base_total = sum(totals.values()) if totals else 0
    tip_pct = bill["tip_pct"] or 0
    tip_total = base_total * (tip_pct / 100)
    grand_total = base_total + tip_total

    currency_symbol = CURRENCY_SYMBOLS.get(bill["currency"], "$")

    return render_template(
        "shared.html",
        bill=bill,
        currency_symbol=currency_symbol,
        grand_total=grand_total,
        tip_total=tip_total,
    )


# ──────────────────────────────────────────────────────────
#  ENDPOINT: GET /api/history — cuentas del visitante actual
# ──────────────────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    """Devuelve las últimas cuentas creadas por este visitante (cookie)."""
    history = db.get_history_for_visitor(g.visitor_id, limit=20)
    return jsonify({"bills": history})


# ──────────────────────────────────────────────────────────
#  ENDPOINT: POST /api/scan-receipt — OCR de una boleta (Fase 3)
# ──────────────────────────────────────────────────────────

MAX_RECEIPT_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


@app.route("/api/scan-receipt", methods=["POST"])
def api_scan_receipt():
    """
    Recibe una foto de boleta (multipart/form-data, campo "image"), la
    procesa con Tesseract y devuelve una lista de ítems candidatos.

    El OCR nunca es perfecto: si no logra extraer nada usable, igual
    responde success=true con items=[] — no es un error, es una boleta
    difícil. success=false es solo para fallas reales (imagen corrupta,
    Tesseract no instalado, etc.).
    """
    file = request.files.get("image")
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "No se recibió ninguna imagen."}), 400

    image_bytes = file.read()
    if len(image_bytes) > MAX_RECEIPT_IMAGE_BYTES:
        return jsonify({"success": False, "error": "La imagen supera los 10MB permitidos."}), 400

    try:
        raw_text = ocr.extract_text(image_bytes)
    except ocr.OCRError as e:
        app.logger.warning(f"OCR failed: {e}")
        return jsonify({"success": False, "error": str(e)})

    items = ocr.parse_receipt_text(raw_text)

    return jsonify({
        "success": True,
        "items": items,
        "raw_text": raw_text,
    })


# ──────────────────────────────────────────────────────────
#  ARRANQUE
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Este bloque solo corre con "python app.py" (desarrollo local).
    # En producción, Gunicorn importa el objeto `app` directamente y lo
    # sirve él mismo — este código ni siquiera se ejecuta ahí.
    #
    # FLASK_DEBUG por defecto queda en "1" para no cambiar el flujo de
    # desarrollo local de siempre; en Render simplemente no se define.
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug, host="0.0.0.0", port=port)

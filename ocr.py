"""
Check Please! — OCR de boletas (Fase 3)
========================================
Dos funciones separadas y testeables a propósito:
  - extract_text(): SOLO llama a Tesseract y devuelve texto crudo.
  - parse_receipt_text(): SOLO interpreta ese texto en una lista de ítems.

Mantenerlas separadas permite reemplazar el motor de OCR más adelante
(por ejemplo con Claude Vision en una versión Pro) sin tocar el parser.
"""

import io
import os
import platform
import re

import pytesseract
from PIL import Image, ImageOps

# ──────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE TESSERACT
# ──────────────────────────────────────────────────────────

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# En Windows el instalador oficial no siempre agrega tesseract al PATH,
# y sumar paquetes de idioma al tessdata del sistema requiere ser
# administrador. Por eso el proyecto trae su propia carpeta tessdata/
# (con eng.traineddata y spa.traineddata) y la usamos si existe.
# En Mac/Linux (ver README) el binario y los idiomas quedan instalados
# a nivel de sistema, así que ahí no hace falta nada de esto.
_LOCAL_TESSDATA = os.path.join(_THIS_DIR, "tessdata")

if platform.system() == "Windows":
    _default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_win_path):
        pytesseract.pytesseract.tesseract_cmd = _default_win_path

# pytesseract no pasa por una shell, así que --tessdata-dir "con comillas"
# como config string no funciona (las comillas quedan pegadas al path).
# La forma correcta de apuntar a una carpeta tessdata alternativa es la
# variable de entorno TESSDATA_PREFIX.
if os.path.isdir(_LOCAL_TESSDATA) and os.listdir(_LOCAL_TESSDATA):
    os.environ["TESSDATA_PREFIX"] = _LOCAL_TESSDATA

# Idiomas que carga Tesseract al leer una boleta. La app es multi-idioma,
# así que probamos español e inglés juntos.
OCR_LANGS = "spa+eng"


class OCRError(Exception):
    """Se lanza cuando Tesseract no pudo procesar la imagen (no cuando
    simplemente no encontró texto — eso es un resultado válido, no un error)."""
    pass


# ──────────────────────────────────────────────────────────
#  extract_text: SOLO corre OCR, no interpreta nada
# ──────────────────────────────────────────────────────────

def extract_text(image_path_or_bytes):
    """
    Corre Tesseract sobre una imagen y devuelve el texto crudo detectado.
    Acepta una ruta de archivo (str) o los bytes crudos de la imagen.
    Lanza OCRError si la imagen no se puede abrir o Tesseract falla.
    """
    try:
        if isinstance(image_path_or_bytes, (bytes, bytearray)):
            img = Image.open(io.BytesIO(image_path_or_bytes))
        else:
            img = Image.open(image_path_or_bytes)
        img.load()  # fuerza la decodificación ahora, para detectar imágenes corruptas
    except Exception as e:
        raise OCRError(f"No se pudo abrir la imagen: {e}")

    img = _preprocess(img)

    try:
        return pytesseract.image_to_string(img, lang=OCR_LANGS)
    except pytesseract.TesseractNotFoundError:
        raise OCRError(
            "Tesseract no está instalado o no se encuentra en el sistema. "
            "Ver README para instrucciones de instalación."
        )
    except Exception as e:
        raise OCRError(f"Tesseract falló al procesar la imagen: {e}")


def _preprocess(img):
    """
    Mejora la imagen antes del OCR. Las fotos de boletas suelen tener
    sombras, poca luz o quedar chicas — esto ayuda bastante a la precisión:
      - escala de grises (Tesseract no usa el color de todos modos)
      - autocontraste (realza texto contra el fondo)
      - agrandar si la imagen es muy chica
    """
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    if img.width < 1000:
        scale = 1000 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


# ──────────────────────────────────────────────────────────
#  parse_receipt_text: SOLO interpreta texto, no toca Tesseract
# ──────────────────────────────────────────────────────────

# Palabras que indican que la línea es encabezado/pie de boleta y no un
# ítem real (en español e inglés, ya que la app es multi-idioma).
IGNORE_KEYWORDS = [
    "total", "subtotal", "iva", "propina", "gracias", "thank you", "thanks",
    "cashier", "cajero", "mesa", "table", "fecha", "date", "servicio",
    "cambio", "change", "efectivo", "cash", "tarjeta", "card", "ticket",
    "folio", "rut", "nit", "mesero", "waiter", "server", "bienvenido",
    "welcome", "visita", "alimentos", "bebidas", "chk", "gst",
]

# "2x Cerveza" / "2 x Cerveza" -> cantidad al inicio de la línea.
_QTY_PREFIX_RE = re.compile(r"^\s*(\d{1,2})\s*[xX]\s+")

# Un precio cerca del final de la línea: símbolo opcional + dígitos con
# separador de miles y/o decimales opcionales. Ej: "24.00", "9,00",
# "$12.500", "1.234,56".
_PRICE_RE = re.compile(r"(?:\$|S/\.?|R\$)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+)\s*$")


def parse_receipt_text(raw_text):
    """
    Convierte el texto crudo de Tesseract en una lista de ítems candidatos:
    [{"name": str, "price": float|None, "qty": int, "confidence": str}, ...]

    Es una heurística basada en regex, no magia: la pantalla de revisión
    del frontend es donde el usuario corrige lo que esto no adivinó bien.
    """
    items = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if len(line) <= 2:
            continue  # línea vacía o ruido de 1-2 caracteres

        if any(kw in line.lower() for kw in IGNORE_KEYWORDS):
            continue  # encabezado / pie de boleta conocido

        price, name, confidence = _extract_price_and_name(line)
        qty, name = _extract_qty(name)

        if price is None and len(name) < 3:
            continue  # ni precio ni texto sustancial: probablemente ruido

        items.append({
            "name": name,
            "price": price,
            "qty": qty,
            "confidence": confidence,
        })
    return items


def _extract_price_and_name(line):
    """Separa una línea en (precio, nombre, confianza)."""
    match = _PRICE_RE.search(line)
    if not match:
        return None, line.strip(" -.:"), "low"

    price, confidence = _normalize_price(match.group(1))
    name = line[:match.start()].strip(" -.:$")
    if not name:
        name = line.strip()
    if price is None:
        confidence = "low"
    return price, name, confidence


def _normalize_price(raw):
    """
    Convierte el string de precio detectado a un float. El problema: '.' y
    ',' pueden ser separador decimal O de miles según el país (24.00 vs
    12.500). Heurística: si aparecen ambos, el último es el decimal; si
    aparece uno solo, 2 dígitos después = decimal, 3 dígitos = miles.
    Cuando hay que adivinar, la confianza baja a "medium".
    """
    s = raw.strip()
    has_dot = "." in s
    has_comma = "," in s
    confidence = "high"

    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            decimal_sep, thousands_sep = ",", "."
        else:
            decimal_sep, thousands_sep = ".", ","
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
        confidence = "medium"
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        digits_after = len(s.split(sep)[-1])
        if digits_after == 2:
            s = s.replace(sep, ".")
        elif digits_after == 3:
            s = s.replace(sep, "")
            confidence = "medium"
        else:
            s = s.replace(sep, ".")
            confidence = "medium"
    else:
        if len(s) > 3:
            confidence = "medium"  # entero largo sin separador: ¿le faltan los centavos?

    try:
        return round(float(s), 2), confidence
    except ValueError:
        return None, "low"


def _extract_qty(name):
    """Si el nombre empieza con "2x " o similar, extrae la cantidad."""
    m = _QTY_PREFIX_RE.match(name)
    if m:
        return int(m.group(1)), name[m.end():].strip()
    return 1, name

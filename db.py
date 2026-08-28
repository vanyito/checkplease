"""
Check Please! — Capa de base de datos (Fase 2 + Fase 4)
==========================================================
En desarrollo local usa SQLite (un solo archivo, sin nada que instalar).
En producción (Render) usa PostgreSQL, porque el disco de Render es
efímero y un archivo SQLite se perdería en cada redeploy.

La elección es automática: si existe la variable de entorno
DATABASE_URL (Render la provee sola al conectar una base de datos),
se usa PostgreSQL. Si no existe —como en tu computador—, se sigue
usando SQLite. Así el flujo de desarrollo local no cambia en nada.

El resto del archivo (create_bill, get_bill_by_share_id, etc.) está
escrito una sola vez, sin ifs por motor de base de datos: get_db()
devuelve algo que se comporta igual en ambos casos (conn.execute(sql,
params) con placeholders "?", filas legibles como diccionario).
"""

import sqlite3
import json
import os
import random
import string
from datetime import datetime, timezone

# Si Render (u otro proveedor) puso DATABASE_URL, usamos PostgreSQL.
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

# Solo importamos psycopg2 si realmente hace falta: así seguir
# desarrollando en local con SQLite no depende de tenerlo instalado,
# aunque esté en requirements.txt para cuando se despliegue.
if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

# El archivo .db vive junto a app.py (solo se usa en modo SQLite).
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkplease.db")

# Alfabeto para los share_id: alfanumérico, sin caracteres que se
# confunden visualmente entre sí (0/O/o, 1/l/I).
SHARE_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
SHARE_ID_LENGTH = 7


class _PostgresConn:
    """
    Adaptador delgado para que el resto de este archivo pueda escribir
    conn.execute(sql, params).fetchone() igual que con sqlite3, aunque
    psycopg2 en realidad necesita abrir un cursor aparte para cada
    consulta. También traduce el placeholder "?" (estilo sqlite3) a
    "%s" (estilo psycopg2) para no tener que escribir cada query dos
    veces.
    """
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    """
    Abre una conexión nueva a la base de datos (PostgreSQL o SQLite
    según corresponda). En ambos casos las filas devueltas se pueden
    leer como diccionario: row["share_id"], dict(row).
    """
    if USE_POSTGRES:
        return _PostgresConn(psycopg2.connect(DATABASE_URL))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn, table, column):
    """Chequeo portable de si una columna ya existe, para migraciones livianas."""
    if USE_POSTGRES:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        return row is not None
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db():
    """
    Crea la tabla `bills` si todavía no existe. Se llama una vez al
    arrancar la app (ver app.py). No borra datos si la tabla ya existe.
    """
    conn = get_db()
    try:
        # El autoincremento se escribe distinto en cada motor:
        # SERIAL (Postgres) vs INTEGER ... AUTOINCREMENT (SQLite).
        id_column = "id SERIAL PRIMARY KEY" if USE_POSTGRES else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS bills (
                {id_column},
                share_id    TEXT UNIQUE NOT NULL,
                visitor_id  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                title       TEXT,
                currency    TEXT NOT NULL,
                lang        TEXT NOT NULL,
                tip_pct     REAL DEFAULT 0,
                payload     TEXT NOT NULL,
                finalized   INTEGER DEFAULT 0
            )
        """)
        # Índice para que /api/history (filtra por visitor_id) sea rápido.
        # CREATE INDEX IF NOT EXISTS existe en ambos motores por igual.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bills_visitor
            ON bills(visitor_id, created_at DESC)
        """)
        # Migración liviana: si la tabla ya existía de antes de agregar la
        # edición colaborativa, le falta la columna `finalized`. La
        # agregamos sin tocar los datos existentes
        # — las cuentas viejas quedan como finalized=0 (se pueden re-abrir
        # para editar, que es un comportamiento razonable por defecto).
        if not _column_exists(conn, "bills", "finalized"):
            conn.execute("ALTER TABLE bills ADD COLUMN finalized INTEGER DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


def _generate_share_id(conn):
    """
    Genera un código corto único para la URL /s/<share_id>.
    Prueba códigos al azar hasta encontrar uno que no exista todavía
    (la probabilidad de choque es mínima, pero igual lo verificamos).
    """
    while True:
        candidate = "".join(random.choices(SHARE_ID_ALPHABET, k=SHARE_ID_LENGTH))
        exists = conn.execute(
            "SELECT 1 FROM bills WHERE share_id = ?", (candidate,)
        ).fetchone()
        if not exists:
            return candidate


def create_bill(visitor_id, title, currency, lang, tip_pct, payload_dict):
    """
    Guarda una cuenta nueva y devuelve su share_id.
    `payload_dict` es un diccionario de Python; se serializa a JSON
    para guardarlo en una sola columna de texto.
    """
    conn = get_db()
    try:
        share_id = _generate_share_id(conn)
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO bills (share_id, visitor_id, created_at, title, currency, lang, tip_pct, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                share_id,
                visitor_id,
                created_at,
                title or None,
                currency,
                lang,
                tip_pct,
                json.dumps(payload_dict, ensure_ascii=False),
            ),
        )
        conn.commit()
        return share_id
    finally:
        conn.close()


def update_bill(share_id, title, currency, lang, tip_pct, payload_dict):
    """
    Actualiza una cuenta existente (edición colaborativa: cualquiera con
    el link puede seguir agregando gente/ítems mientras no esté
    finalizada). Devuelve True si se guardó, False si la cuenta no
    existe o ya fue finalizada (para no pisar un resumen ya cerrado).
    """
    conn = get_db()
    try:
        cur = conn.execute(
            """
            UPDATE bills
            SET title = ?, currency = ?, lang = ?, tip_pct = ?, payload = ?
            WHERE share_id = ? AND finalized = 0
            """,
            (
                title or None,
                currency,
                lang,
                tip_pct,
                json.dumps(payload_dict, ensure_ascii=False),
                share_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def finalize_bill(share_id):
    """
    Marca una cuenta como terminada: a partir de ahora su link muestra
    el resumen de solo lectura en vez de la app editable, y ya no admite
    más ediciones vía update_bill(). Devuelve True si la cuenta existía.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE bills SET finalized = 1 WHERE share_id = ?", (share_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_bill_by_share_id(share_id):
    """
    Busca una cuenta por su código de link. Devuelve un dict con el
    payload ya deserializado, o None si no existe.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM bills WHERE share_id = ?", (share_id,)
        ).fetchone()
        if not row:
            return None
        bill = dict(row)
        bill["payload"] = json.loads(bill["payload"])
        return bill
    finally:
        conn.close()


def get_history_for_visitor(visitor_id, limit=20):
    """
    Devuelve las últimas `limit` cuentas creadas por este visitante,
    de más reciente a más antigua. Cada elemento incluye el total ya
    calculado (a partir del payload) para no tener que recalcularlo
    en el frontend.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT share_id, title, created_at, currency, tip_pct, payload
            FROM bills
            WHERE visitor_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (visitor_id, limit),
        ).fetchall()

        history = []
        for row in rows:
            payload = json.loads(row["payload"])
            totals = payload.get("totals", {})
            base_total = sum(totals.values()) if totals else 0
            grand_total = base_total * (1 + (row["tip_pct"] or 0) / 100)
            history.append({
                "share_id": row["share_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "currency": row["currency"],
                "total": round(grand_total, 2),
            })
        return history
    finally:
        conn.close()

"""Persistencia en SQLite: prospectos, evidencias con fuente, historial, corridas,
mensajes, registro de contactos y lista de exclusión (Ley 1581)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

ESTADOS_COMERCIALES = [
    "Nuevo prospecto",
    "Pendiente de investigación",
    "Prospecto calificado",
    "Pendiente de contacto",
    "Contactado",
    "Respondió",
    "Reunión programada",
    "Propuesta enviada",
    "Negociación",
    "Cliente ganado",
    "Cliente perdido",
    "Descartado",
]

CONFIANZA = ["alta", "media", "baja"]
VERIFICACION = ["confirmado", "estimado", "no_disponible"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospectos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,
    razon_social TEXT,
    sector TEXT,
    actividad TEXT,
    ciudad TEXT,
    direccion TEXT,
    sitio_web TEXT,
    dominio TEXT,
    telefono TEXT,
    telefono_norm TEXT,
    whatsapp TEXT,
    correo TEXT,
    formulario_contacto TEXT,
    instagram TEXT,
    facebook TEXT,
    linkedin TEXT,
    tiktok TEXT,
    contacto_nombre TEXT,
    contacto_cargo TEXT,
    contacto_fuente_url TEXT,
    tamano_estimado TEXT,
    num_sedes INTEGER DEFAULT 1,
    rating REAL,
    num_resenas INTEGER,
    nivel_precio TEXT,
    estado_negocio TEXT,
    google_place_id TEXT,
    google_maps_url TEXT,
    descripcion TEXT,
    senales TEXT DEFAULT '{}',
    servicio_recomendado TEXT,
    problema_potencial TEXT,
    justificacion TEXT,
    puntaje REAL,
    clasificacion TEXT,
    puntaje_detalle TEXT DEFAULT '{}',
    ficha TEXT DEFAULT '{}',
    estado_comercial TEXT DEFAULT 'Nuevo prospecto',
    observaciones TEXT DEFAULT '',
    excluido INTEGER DEFAULT 0,
    motivo_exclusion TEXT,
    corrida_id INTEGER,
    fecha_investigacion TEXT,
    fecha_actualizacion TEXT,
    ultimo_contacto TEXT,
    intentos_contacto INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prospectos_place ON prospectos(google_place_id) WHERE google_place_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_prospectos_norm ON prospectos(nombre_norm);
CREATE INDEX IF NOT EXISTS ix_prospectos_dominio ON prospectos(dominio);
CREATE INDEX IF NOT EXISTS ix_prospectos_tel ON prospectos(telefono_norm);

CREATE TABLE IF NOT EXISTS sedes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospecto_id INTEGER NOT NULL REFERENCES prospectos(id) ON DELETE CASCADE,
    place_id TEXT UNIQUE,
    nombre TEXT,
    direccion TEXT,
    ciudad TEXT,
    telefono TEXT,
    maps_url TEXT,
    lat REAL,
    lng REAL,
    fecha TEXT
);

CREATE TABLE IF NOT EXISTS datos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospecto_id INTEGER NOT NULL REFERENCES prospectos(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,
    valor TEXT,
    fuente TEXT NOT NULL,
    url TEXT,
    fecha TEXT NOT NULL,
    confianza TEXT NOT NULL,
    verificacion TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_datos_prospecto ON datos(prospecto_id);

CREATE TABLE IF NOT EXISTS historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospecto_id INTEGER REFERENCES prospectos(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    evento TEXT NOT NULL,
    detalle TEXT,
    corrida_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_historial_prospecto ON historial(prospecto_id);

CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instruccion TEXT NOT NULL,
    plan TEXT DEFAULT '{}',
    estado TEXT NOT NULL,
    creada TEXT NOT NULL,
    terminada TEXT,
    reporte TEXT DEFAULT '{}',
    log TEXT DEFAULT '',
    error TEXT
);

CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospecto_id INTEGER NOT NULL REFERENCES prospectos(id) ON DELETE CASCADE,
    canal TEXT NOT NULL,
    asunto TEXT,
    cuerpo TEXT NOT NULL,
    necesidad TEXT,
    servicio TEXT,
    estado TEXT NOT NULL DEFAULT 'borrador',
    generado_por TEXT,
    creado TEXT NOT NULL,
    aprobado_en TEXT,
    enviado_en TEXT
);

CREATE TABLE IF NOT EXISTS contactos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospecto_id INTEGER NOT NULL REFERENCES prospectos(id) ON DELETE CASCADE,
    canal TEXT NOT NULL,
    fecha TEXT NOT NULL,
    resultado TEXT,
    nota TEXT
);

CREATE TABLE IF NOT EXISTS exclusiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    valor TEXT NOT NULL,
    motivo TEXT,
    fecha TEXT NOT NULL,
    UNIQUE(tipo, valor)
);
"""

JSON_FIELDS = {"senales", "puntaje_detalle", "ficha"}
PROSPECT_COLUMNS = {
    "nombre", "nombre_norm", "razon_social", "sector", "actividad", "ciudad", "direccion", "sitio_web",
    "dominio", "telefono", "telefono_norm", "whatsapp", "correo", "formulario_contacto", "instagram",
    "facebook", "linkedin", "tiktok", "contacto_nombre", "contacto_cargo", "contacto_fuente_url",
    "tamano_estimado", "num_sedes", "rating", "num_resenas", "nivel_precio", "estado_negocio",
    "google_place_id", "google_maps_url", "descripcion", "senales", "servicio_recomendado",
    "problema_potencial", "justificacion", "puntaje", "clasificacion", "puntaje_detalle", "ficha",
    "estado_comercial", "observaciones", "excluido", "motivo_exclusion", "corrida_id",
    "fecha_investigacion", "fecha_actualizacion", "ultimo_contacto", "intentos_contacto",
}


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in JSON_FIELDS & d.keys():
        try:
            d[f] = json.loads(d[f] or "{}")
        except (TypeError, json.JSONDecodeError):
            d[f] = {}
    for f in ("plan", "reporte"):
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f] or "{}")
            except json.JSONDecodeError:
                d[f] = {}
    return d


def _encode(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if k in JSON_FIELDS and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        out[k] = v
    return out


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mem_conn: sqlite3.Connection | None = None
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self.path == ":memory:":
                if self._mem_conn is None:
                    self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
                    self._mem_conn.row_factory = sqlite3.Row
                    self._mem_conn.execute("PRAGMA foreign_keys=ON")
                conn = self._mem_conn
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                return
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Prospectos
    # ------------------------------------------------------------------
    def insert_prospect(self, values: dict) -> int:
        values = {k: v for k, v in _encode(values).items() if k in PROSPECT_COLUMNS}
        values.setdefault("fecha_investigacion", now())
        values.setdefault("fecha_actualizacion", values["fecha_investigacion"])
        cols = ", ".join(values)
        qs = ", ".join("?" for _ in values)
        with self.connect() as c:
            cur = c.execute(f"INSERT INTO prospectos ({cols}) VALUES ({qs})", list(values.values()))
            return int(cur.lastrowid)

    def update_prospect(self, pid: int, values: dict, touch: bool = True) -> None:
        values = {k: v for k, v in _encode(values).items() if k in PROSPECT_COLUMNS}
        if touch:
            values["fecha_actualizacion"] = now()
        if not values:
            return
        sets = ", ".join(f"{k}=?" for k in values)
        with self.connect() as c:
            c.execute(f"UPDATE prospectos SET {sets} WHERE id=?", [*values.values(), pid])

    def get_prospect(self, pid: int) -> dict | None:
        with self.connect() as c:
            return _decode(c.execute("SELECT * FROM prospectos WHERE id=?", (pid,)).fetchone())

    def delete_prospect(self, pid: int) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM prospectos WHERE id=?", (pid,))

    def find_prospect(self, *, place_id=None, dominio=None, telefono_norm=None, nombre_norm=None, ciudad=None) -> dict | None:
        """Busca un prospecto existente por las claves de deduplicación, en orden de fuerza."""
        with self.connect() as c:
            if place_id:
                r = c.execute("SELECT p.* FROM prospectos p WHERE google_place_id=? UNION "
                              "SELECT p.* FROM prospectos p JOIN sedes s ON s.prospecto_id=p.id WHERE s.place_id=?",
                              (place_id, place_id)).fetchone()
                if r:
                    return _decode(r)
            if dominio:
                r = c.execute("SELECT * FROM prospectos WHERE dominio=?", (dominio,)).fetchone()
                if r:
                    return _decode(r)
            if telefono_norm:
                r = c.execute("SELECT * FROM prospectos WHERE telefono_norm=?", (telefono_norm,)).fetchone()
                if r:
                    return _decode(r)
            if nombre_norm:
                # Mismo nombre en el área metropolitana = misma empresa (otra sede)
                r = c.execute("SELECT * FROM prospectos WHERE nombre_norm=?", (nombre_norm,)).fetchone()
                if r:
                    return _decode(r)
        return None

    def list_prospects(
        self,
        *,
        sector: str | None = None,
        ciudad: str | None = None,
        estado: str | None = None,
        clasificacion: str | None = None,
        servicio: str | None = None,
        q: str | None = None,
        incluir_excluidos: bool = False,
        orden: str = "puntaje",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._filters(sector, ciudad, estado, clasificacion, servicio, q, incluir_excluidos)
        order = {
            "puntaje": "puntaje IS NULL, puntaje DESC, nombre",
            "nombre": "nombre COLLATE NOCASE",
            "fecha": "fecha_investigacion DESC",
            "actualizacion": "fecha_actualizacion DESC",
            "ciudad": "ciudad, puntaje DESC",
        }.get(orden, "puntaje DESC")
        sql = f"SELECT * FROM prospectos {where} ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        with self.connect() as c:
            return [_decode(r) for r in c.execute(sql, params).fetchall()]

    def count_prospects(self, **filters) -> int:
        where, params = self._filters(
            filters.get("sector"), filters.get("ciudad"), filters.get("estado"), filters.get("clasificacion"),
            filters.get("servicio"), filters.get("q"), filters.get("incluir_excluidos", False),
        )
        with self.connect() as c:
            return int(c.execute(f"SELECT COUNT(*) FROM prospectos {where}", params).fetchone()[0])

    @staticmethod
    def _filters(sector, ciudad, estado, clasificacion, servicio, q, incluir_excluidos):
        clauses, params = [], []
        if not incluir_excluidos:
            clauses.append("excluido=0")
        for col, val in (("sector", sector), ("ciudad", ciudad), ("estado_comercial", estado),
                         ("clasificacion", clasificacion), ("servicio_recomendado", servicio)):
            if val:
                clauses.append(f"{col}=?")
                params.append(val)
        if q:
            clauses.append("(nombre LIKE ? OR razon_social LIKE ? OR nombre_norm LIKE ? OR direccion LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like, like, like]
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def distinct(self, column: str) -> list[str]:
        assert column in {"sector", "ciudad", "estado_comercial", "clasificacion", "servicio_recomendado"}
        with self.connect() as c:
            return [r[0] for r in c.execute(
                f"SELECT DISTINCT {column} FROM prospectos WHERE {column} IS NOT NULL AND {column}!='' ORDER BY 1")]

    def group_count(self, column: str) -> list[tuple[str, int]]:
        assert column in {"sector", "ciudad", "estado_comercial", "clasificacion", "servicio_recomendado"}
        with self.connect() as c:
            return [(r[0] or "Sin dato", r[1]) for r in c.execute(
                f"SELECT {column}, COUNT(*) FROM prospectos WHERE excluido=0 GROUP BY {column} ORDER BY 2 DESC")]

    def leads_by_week(self, weeks: int = 12) -> list[tuple[str, int]]:
        since = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        with self.connect() as c:
            rows = c.execute(
                "SELECT strftime('%Y-%W', fecha_investigacion) w, COUNT(*) FROM prospectos "
                "WHERE fecha_investigacion >= ? GROUP BY w ORDER BY w", (since,)).fetchall()
        return [(r[0], r[1]) for r in rows]

    # ------------------------------------------------------------------
    # Sedes, evidencias e historial
    # ------------------------------------------------------------------
    def add_branch(self, pid: int, branch: dict) -> bool:
        with self.connect() as c:
            try:
                c.execute(
                    "INSERT INTO sedes (prospecto_id, place_id, nombre, direccion, ciudad, telefono, maps_url, lat, lng, fecha)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, branch.get("place_id"), branch.get("nombre"), branch.get("direccion"), branch.get("ciudad"),
                     branch.get("telefono"), branch.get("maps_url"), branch.get("lat"), branch.get("lng"), now()))
            except sqlite3.IntegrityError:
                return False
            n = c.execute("SELECT COUNT(*) FROM sedes WHERE prospecto_id=?", (pid,)).fetchone()[0]
            c.execute("UPDATE prospectos SET num_sedes=MAX(COALESCE(num_sedes,1), ?) WHERE id=?", (n, pid))
        return True

    def branches(self, pid: int) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sedes WHERE prospecto_id=? ORDER BY id", (pid,))]

    def add_evidence(self, pid: int, campo: str, valor: Any, fuente: str, url: str | None,
                     confianza: str, verificacion: str) -> None:
        assert confianza in CONFIANZA and verificacion in VERIFICACION, (confianza, verificacion)
        if isinstance(valor, (dict, list)):
            valor = json.dumps(valor, ensure_ascii=False)
        with self.connect() as c:
            dup = c.execute(
                "SELECT id FROM datos WHERE prospecto_id=? AND campo=? AND COALESCE(valor,'')=COALESCE(?,'') AND fuente=?",
                (pid, campo, None if valor is None else str(valor), fuente)).fetchone()
            if dup:
                c.execute("UPDATE datos SET fecha=?, url=COALESCE(?, url) WHERE id=?", (now(), url, dup[0]))
                return
            c.execute(
                "INSERT INTO datos (prospecto_id, campo, valor, fuente, url, fecha, confianza, verificacion)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (pid, campo, None if valor is None else str(valor), fuente, url, now(), confianza, verificacion))

    def evidence(self, pid: int) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM datos WHERE prospecto_id=? ORDER BY campo, fecha DESC", (pid,))]

    def log_event(self, pid: int | None, evento: str, detalle: str = "", corrida_id: int | None = None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO historial (prospecto_id, fecha, evento, detalle, corrida_id) VALUES (?,?,?,?,?)",
                      (pid, now(), evento, detalle, corrida_id))

    def history(self, pid: int) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM historial WHERE prospecto_id=? ORDER BY id DESC", (pid,))]

    # ------------------------------------------------------------------
    # Corridas (ejecuciones del agente)
    # ------------------------------------------------------------------
    def create_run(self, instruccion: str) -> int:
        with self.connect() as c:
            cur = c.execute("INSERT INTO corridas (instruccion, estado, creada) VALUES (?,?,?)",
                            (instruccion, "en cola", now()))
            return int(cur.lastrowid)

    def update_run(self, rid: int, **values) -> None:
        for k in ("plan", "reporte"):
            if k in values and not isinstance(values[k], str):
                values[k] = json.dumps(values[k], ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in values)
        with self.connect() as c:
            c.execute(f"UPDATE corridas SET {sets} WHERE id=?", [*values.values(), rid])

    def append_run_log(self, rid: int, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self.connect() as c:
            c.execute("UPDATE corridas SET log = COALESCE(log,'') || ? WHERE id=?", (f"[{stamp}] {line}\n", rid))

    def get_run(self, rid: int) -> dict | None:
        with self.connect() as c:
            return _decode(c.execute("SELECT * FROM corridas WHERE id=?", (rid,)).fetchone())

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self.connect() as c:
            return [_decode(r) for r in c.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limit,))]

    def prospects_of_run(self, rid: int) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                "SELECT DISTINCT p.* FROM prospectos p JOIN historial h ON h.prospecto_id=p.id "
                "WHERE h.corrida_id=? ORDER BY p.puntaje DESC", (rid,)).fetchall()
            return [_decode(r) for r in rows]

    # ------------------------------------------------------------------
    # Mensajes y contactos
    # ------------------------------------------------------------------
    def add_message(self, pid: int, canal: str, cuerpo: str, *, asunto=None, necesidad=None, servicio=None,
                    generado_por="plantilla") -> int:
        with self.connect() as c:
            cur = c.execute(
                "INSERT INTO mensajes (prospecto_id, canal, asunto, cuerpo, necesidad, servicio, estado, generado_por, creado)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, canal, asunto, cuerpo, necesidad, servicio, "borrador", generado_por, now()))
            return int(cur.lastrowid)

    def messages(self, pid: int | None = None, estado: str | None = None) -> list[dict]:
        sql = ("SELECT m.*, p.nombre AS prospecto_nombre, p.puntaje AS prospecto_puntaje FROM mensajes m "
               "JOIN prospectos p ON p.id=m.prospecto_id WHERE 1=1")
        params: list = []
        if pid is not None:
            sql += " AND m.prospecto_id=?"
            params.append(pid)
        if estado:
            sql += " AND m.estado=?"
            params.append(estado)
        sql += " ORDER BY m.id" + ("" if pid is not None else " DESC")
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params)]

    def get_message(self, mid: int) -> dict | None:
        with self.connect() as c:
            r = c.execute("SELECT * FROM mensajes WHERE id=?", (mid,)).fetchone()
            return dict(r) if r else None

    def update_message(self, mid: int, **values) -> None:
        sets = ", ".join(f"{k}=?" for k in values)
        with self.connect() as c:
            c.execute(f"UPDATE mensajes SET {sets} WHERE id=?", [*values.values(), mid])

    def delete_drafts(self, pid: int) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM mensajes WHERE prospecto_id=? AND estado='borrador'", (pid,))

    def add_contact(self, pid: int, canal: str, resultado: str = "", nota: str = "") -> None:
        with self.connect() as c:
            c.execute("INSERT INTO contactos (prospecto_id, canal, fecha, resultado, nota) VALUES (?,?,?,?,?)",
                      (pid, canal, now(), resultado, nota))
            c.execute("UPDATE prospectos SET ultimo_contacto=?, intentos_contacto=COALESCE(intentos_contacto,0)+1 "
                      "WHERE id=?", (now(), pid))

    def contacts(self, pid: int) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM contactos WHERE prospecto_id=? ORDER BY id DESC", (pid,))]

    # ------------------------------------------------------------------
    # Exclusiones
    # ------------------------------------------------------------------
    def add_suppression(self, tipo: str, valor: str, motivo: str = "") -> None:
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO exclusiones (tipo, valor, motivo, fecha) VALUES (?,?,?,?)",
                      (tipo, valor, motivo, now()))

    def remove_suppression(self, sid: int) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM exclusiones WHERE id=?", (sid,))

    def suppressions(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM exclusiones ORDER BY id DESC")]

    def is_suppressed(self, pairs: Iterable[tuple[str, str | None]]) -> dict | None:
        with self.connect() as c:
            for tipo, valor in pairs:
                if not valor:
                    continue
                r = c.execute("SELECT * FROM exclusiones WHERE tipo=? AND valor=?", (tipo, valor)).fetchone()
                if r:
                    return dict(r)
        return None

    # ------------------------------------------------------------------
    # Duplicados
    # ------------------------------------------------------------------
    def merge_prospects(self, keep_id: int, drop_id: int) -> None:
        """Fusiona `drop_id` dentro de `keep_id` conservando toda la trazabilidad."""
        keep, drop = self.get_prospect(keep_id), self.get_prospect(drop_id)
        if not keep or not drop or keep_id == drop_id:
            raise ValueError("Prospectos inválidos para fusionar")
        fill = {k: drop[k] for k in PROSPECT_COLUMNS - JSON_FIELDS
                if k not in {"nombre", "nombre_norm", "google_place_id", "estado_comercial", "puntaje", "clasificacion"}
                and not keep.get(k) and drop.get(k)}
        with self.connect() as c:
            for table in ("sedes", "datos", "historial", "mensajes", "contactos"):
                c.execute(f"UPDATE {table} SET prospecto_id=? WHERE prospecto_id=?", (keep_id, drop_id))
            if drop.get("google_place_id"):
                c.execute("UPDATE prospectos SET google_place_id=NULL WHERE id=?", (drop_id,))
            n = c.execute("SELECT COUNT(*) FROM sedes WHERE prospecto_id=?", (keep_id,)).fetchone()[0]
            c.execute("DELETE FROM prospectos WHERE id=?", (drop_id,))
        fill["num_sedes"] = max(int(keep.get("num_sedes") or 1), n)
        self.update_prospect(keep_id, fill)
        self.log_event(keep_id, "Fusión de duplicados", f"Se fusionó '{drop['nombre']}' (#{drop_id})")

    def possible_duplicates(self, threshold: float = 0.86, limit: int = 100) -> list[dict]:
        from .normalize import similarity

        with self.connect() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT id, nombre, nombre_norm, ciudad, direccion, telefono_norm, dominio, puntaje FROM prospectos")]
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            buckets.setdefault((r["nombre_norm"] or "")[:3], []).append(r)
        pairs = []
        for group in buckets.values():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    sim = similarity(a["nombre"], b["nombre"])
                    if sim >= threshold:
                        pairs.append({"a": a, "b": b, "similitud": round(sim, 2)})
        pairs.sort(key=lambda x: -x["similitud"])
        return pairs[:limit]

    # ------------------------------------------------------------------
    # Retención
    # ------------------------------------------------------------------
    def purge(self, dias_descartados: int, dias_sin_contacto: int) -> int:
        lim_desc = (datetime.now() - timedelta(days=dias_descartados)).isoformat(sep=" ")
        lim_sin = (datetime.now() - timedelta(days=dias_sin_contacto)).isoformat(sep=" ")
        with self.connect() as c:
            cur = c.execute(
                "DELETE FROM prospectos WHERE (estado_comercial IN ('Descartado','Cliente perdido') OR excluido=1) "
                "AND fecha_actualizacion < ?", (lim_desc,))
            n = cur.rowcount
            cur = c.execute(
                "DELETE FROM prospectos WHERE ultimo_contacto IS NULL AND estado_comercial IN "
                "('Nuevo prospecto','Pendiente de investigación','Prospecto calificado','Pendiente de contacto') "
                "AND fecha_actualizacion < ?", (lim_sin,))
            return n + cur.rowcount

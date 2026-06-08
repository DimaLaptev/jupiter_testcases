"""Python-аналоги SP наполнение_руки и перенос_в_архив."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

PREDSVOD_TABLES = (
    "predsvod_gpb",
    "predsvod_vtb",
    "predsvod_region",
    "predsvod_rsd",
)

_COLS = ", ".join(f"col_{i:02d}" for i in range(1, 25))


def sync_editable_from_predsvod(conn: sqlite3.Connection) -> int:
    """
    Первичное наполнение editable_registry из predsvod_* (если реестр пуст).
    v1: col_01..col_24 → первые 24 поля реестра; portfolio_section из spravochnik_1.
    """
    existing = conn.execute("SELECT COUNT(*) FROM editable_registry").fetchone()[0]
    if existing:
        return 0

    inserted = 0
    for table in PREDSVOD_TABLES:
        source = table.replace("predsvod_", "")
        rows = conn.execute(f"SELECT {_COLS} FROM {table}").fetchall()
        for row in rows:
            pf = _lookup_portfolio(conn, row[3] if len(row) > 3 else None)
            conn.execute(
                """
                INSERT INTO editable_registry (
                    source, portfolio_section,
                    n_zakladnoy, depository, owner, schet_depo, razdel_scheta,
                    quantity, fio, nomer_kd, ngri_v_depo, ngri_v_portfele,
                    vremennoe_snyatie, enc, agent_soprovozhdeniya, pul_zakladnyh,
                    gorod_hraneniya, comment, massiv_po_n, massiv_po_ngri,
                    master_date, investor, servisny_agent, status_eis
                ) VALUES (
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    source,
                    pf,
                    row[0], row[1], row[2], row[3], row[4],
                    row[5], row[6], row[7], row[8], row[9],
                    row[10], row[11], row[12], row[13],
                    row[14], row[15], row[16], row[17],
                    row[18], row[19], row[20], row[21],
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def _lookup_portfolio(conn: sqlite3.Connection, schet: str | None) -> str | None:
    if not schet or not str(schet).strip():
        return None
    row = conn.execute(
        "SELECT col_01 FROM spravochnik_1 WHERE TRIM(col_03) = TRIM(?) LIMIT 1",
        (str(schet).strip(),),
    ).fetchone()
    return row[0] if row else None


def run_napolnenie_ruki(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Аналог exec [наполнение_руки]: ruki_temp → editable_registry.
    col_01..col_08 маппятся на первые 8 полей реестра.
    """
    rows = conn.execute(
        "SELECT col_01, col_02, col_03, col_04, col_05, col_06, col_07, col_08 FROM ruki_temp",
    ).fetchall()
    merged = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO editable_registry (
                source, n_zakladnoy, depository, owner, schet_depo,
                razdel_scheta, quantity, fio, nomer_kd, lock
            ) VALUES ('manual', ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            row,
        )
        merged += 1
    conn.execute("DELETE FROM ruki_temp")
    conn.commit()
    return {"ruki_rows_merged": merged}


def run_perenos_v_archive(conn: sqlite3.Connection, archived_at: str | None = None) -> dict[str, int]:
    """Аналог EXEC [перенос_в_архив]: predsvod_* → predsvod_archive."""
    ts = archived_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    tables_archived = 0
    for table in PREDSVOD_TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count == 0:
            continue
        conn.execute(
            f"""
            INSERT INTO predsvod_archive (source_table, archived_at, {_COLS})
            SELECT ?, ?, {_COLS} FROM {table}
            """,
            (table, ts),
        )
        total += count
        tables_archived += 1
    conn.commit()
    return {"archived_rows": total, "tables_archived": tables_archived, "archived_at": ts}


def run_form_update(
    conn: sqlite3.Connection,
    ngri: str,
    zakladnay: str,
    comment: str,
) -> int:
    """Аналог Форма.txt: UPDATE editable_registry по НГРИ."""
    cur = conn.execute(
        """
        UPDATE editable_registry
        SET lock = 0, n_zakladnoy = ?, comment = ?
        WHERE ngri_v_depo = ?
        """,
        (zakladnay, comment, ngri),
    )
    conn.commit()
    return cur.rowcount

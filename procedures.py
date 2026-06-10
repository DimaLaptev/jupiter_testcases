"""Python-аналоги SP наполнение_руки и перенос_в_архив."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from sql_upload.predsvod_layout import (
    SPRAV1_ACCOUNT_COL,
    SPRAV1_PORTFOLIO_SECTION_COL,
    predsvod_row_to_registry,
)

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
    Маппинг col_01..col_24 по predsvod_layout; portfolio_section из spravochnik_1 col_11.
    """
    existing = conn.execute("SELECT COUNT(*) FROM editable_registry").fetchone()[0]
    if existing:
        return 0

    inserted = 0
    for table in PREDSVOD_TABLES:
        source = table.replace("predsvod_", "")
        rows = conn.execute(f"SELECT {_COLS} FROM {table}").fetchall()
        for row in rows:
            fields = predsvod_row_to_registry(row)
            pf = _lookup_portfolio(conn, fields.get("schet_depo"))
            conn.execute(
                """
                INSERT INTO editable_registry (
                    source, portfolio_section,
                    n_zakladnoy, depository, owner, schet_depo, razdel_scheta,
                    data_priema, quantity, fio, nomer_kd, ngri_v_depo, ngri_v_portfele,
                    vremennoe_snyatie, enc, agent_soprovozhdeniya, pul_zakladnyh,
                    gorod_hraneniya, comment, massiv_po_n, massiv_po_ngri,
                    master_date, investor, servisny_agent, status_eis,
                    data_pogasheniya_eis, status_hraneniya, hranitel
                ) VALUES (
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    source,
                    pf,
                    fields["n_zakladnoy"],
                    fields["depository"],
                    fields["owner"],
                    fields["schet_depo"],
                    fields["razdel_scheta"],
                    fields["data_priema"],
                    fields["quantity"],
                    fields["fio"],
                    fields["nomer_kd"],
                    fields["ngri_v_depo"],
                    fields["ngri_v_portfele"],
                    fields["vremennoe_snyatie"],
                    fields["enc"],
                    fields["agent_soprovozhdeniya"],
                    fields["pul_zakladnyh"],
                    fields["gorod_hraneniya"],
                    fields["comment"],
                    fields["massiv_po_n"],
                    fields["massiv_po_ngri"],
                    fields["master_date"],
                    fields["investor"],
                    fields["servisny_agent"],
                    fields["status_eis"],
                    fields["data_pogasheniya_eis"],
                    fields["status_hraneniya"],
                    fields["hranitel"],
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def _lookup_portfolio(conn: sqlite3.Connection, schet: str | None) -> str | None:
    """
    Раздел КП для листов СВОД_поДЕПО: spravochnik_1 col_11 (новый формат),
    fallback col_01 (legacy 7-col справочник из VBA).
    Ключ: col_03 «Номер счета депo» = predsvod col_05 «Счет депo».
    """
    if not schet or not str(schet).strip():
        return None
    key = str(schet).strip()
    account_col = f"col_{SPRAV1_ACCOUNT_COL:02d}"
    section_col = f"col_{SPRAV1_PORTFOLIO_SECTION_COL:02d}"
    row = conn.execute(
        f"""
        SELECT {section_col}, col_01
        FROM spravochnik_1
        WHERE TRIM({account_col}) = TRIM(?)
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    if not row:
        return None
    section, legacy = row
    if section and str(section).strip():
        return str(section).strip()
    if legacy and str(legacy).strip():
        return str(legacy).strip()
    return None


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

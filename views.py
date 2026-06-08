"""SQLite views для фазы depo (v1-аналог SQL Server VIEW_*)."""

from __future__ import annotations

import sqlite3

_VIEW_NAMES = (
    "v_sbor_reestra",
    "v_proverka_zagruzki",
    "v_dubli_ngri",
    "v_dubli_zakladnye",
)

# Порядок колонок v_sbor_reestra (= SBOR_REESTRA_HEADERS).
_SBOR_VIEW_COLS: tuple[str, ...] = (
    "n_zakladnoy",
    "depository",
    "owner",
    "schet_depo",
    "razdel_scheta",
    "quantity",
    "fio",
    "nomer_kd",
    "ngri_v_depo",
    "ngri_v_portfele",
    "vremennoe_snyatie",
    "enc",
    "agent_soprovozhdeniya",
    "pul_zakladnyh",
    "gorod_hraneniya",
    "comment",
    "massiv_po_n",
    "massiv_po_ngri",
    "master_date",
    "investor",
    "servisny_agent",
    "status_eis",
    "data_pogasheniya_eis",
    "status_hraneniya",
    "hranitel",
    "data_priema",
    "schet_depo2",
    "razdel",
    "nomer_kd2",
    "sverka_s_defoltami",
    "sovpad",
)

_SBOR_SELECT = """
SELECT
    n_zakladnoy,
    depository,
    owner,
    schet_depo,
    razdel_scheta,
    quantity,
    fio,
    nomer_kd,
    ngri_v_depo,
    ngri_v_portfele,
    vremennoe_snyatie,
    enc,
    agent_soprovozhdeniya,
    pul_zakladnyh,
    gorod_hraneniya,
    comment,
    massiv_po_n,
    massiv_po_ngri,
    master_date,
    investor,
    servisny_agent,
    status_eis,
    data_pogasheniya_eis,
    status_hraneniya,
    hranitel,
    data_priema,
    schet_depo2,
    razdel,
    nomer_kd2,
    sverka_s_defoltami,
    sovpad,
    portfolio_section
FROM editable_registry
"""

_V_PROVERKA = """
CREATE VIEW v_proverka_zagruzki AS
SELECT
    COALESCE(s.col_03, p.schet_depo, w.schet) AS account_text,
    COALESCE(p.quantity, w.quantity, '0') AS quantity,
    COALESCE(s.col_02, p.depository, w.depository, '') AS depository
FROM (
    SELECT DISTINCT col_03, col_02 FROM spravochnik_1 WHERE col_03 IS NOT NULL AND col_03 != ''
) s
LEFT JOIN (
    SELECT schet_depo, quantity, depository FROM editable_registry
    WHERE schet_depo IS NOT NULL AND schet_depo != ''
) p ON TRIM(p.schet_depo) = TRIM(s.col_03)
LEFT JOIN (
    SELECT schet,
           json_extract(data_json, '$.col_06') AS quantity,
           json_extract(data_json, '$.col_02') AS depository
    FROM working_mortgage
    WHERE schet IS NOT NULL
) w ON TRIM(w.schet) = TRIM(s.col_03)
WHERE p.schet_depo IS NULL
"""

_V_DUBLI_NGRI = """
CREATE VIEW v_dubli_ngri AS
SELECT
    ngri_v_depo AS ngri_v_depo,
    COUNT(*) AS duplicate_count
FROM editable_registry
WHERE ngri_v_depo IS NOT NULL AND TRIM(ngri_v_depo) != ''
GROUP BY ngri_v_depo
HAVING COUNT(*) > 1
"""

_V_DUBLI_ZAKLADNYE = """
CREATE VIEW v_dubli_zakladnye AS
SELECT
    n_zakladnoy AS n_zakladnoy,
    COUNT(*) AS duplicate_count
FROM editable_registry
WHERE n_zakladnoy IS NOT NULL AND TRIM(n_zakladnoy) != ''
GROUP BY n_zakladnoy
HAVING COUNT(*) > 1
"""


def drop_depo_views(conn: sqlite3.Connection) -> None:
    for name in _VIEW_NAMES:
        conn.execute(f"DROP VIEW IF EXISTS {name}")


def ensure_depo_views(conn: sqlite3.Connection) -> None:
    """Пересоздать view после изменения editable_registry."""
    drop_depo_views(conn)
    conn.execute(f"CREATE VIEW v_sbor_reestra AS {_SBOR_SELECT}")
    conn.executescript(_V_PROVERKA)
    conn.executescript(_V_DUBLI_NGRI)
    conn.executescript(_V_DUBLI_ZAKLADNYE)
    conn.commit()


def sbor_reestra_query(portfolio_section: str) -> tuple[str, tuple[str, ...]]:
    cols = ", ".join(_SBOR_VIEW_COLS)
    sql = f"""
        SELECT {cols}
        FROM v_sbor_reestra
        WHERE portfolio_section = ?
        ORDER BY n_zakladnoy
    """
    return sql, (portfolio_section,)

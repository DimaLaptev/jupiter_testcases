"""Раскладка колонок предсвода и нового справочника (по скринам MAF_SVOD_DEPO)."""

from __future__ import annotations

# Листы промежуточной книги предсвода (скрин 7)
PREDSVOD_SHEETS = {
    "svod_gpb": "GPB",
    "svod_region": "REGION",
    "svod_vtb": "VTBSD",
    "svod_rsd": "RSD_MSG",
}

# Шапка на строке 3, данные с строки 4 (скрины 3–6); VBA raw grid — 24 колонки A–X
PREDSVOD_ROW_START = 4
PREDSVOD_COL_START = 1
PREDSVOD_COL_END = 24
PREDSVOD_LAST_ROW_COL = 5  # «Счет депо» (column E)

# Новый справочник лист 1: 13 колонок A–M (скрин 2), заголовок строка 1, данные со 2
SPRAV1_ROW_START = 2
SPRAV1_COL_END = 13
SPRAV1_ACCOUNT_COL = 3  # C «Номер счета депо»
SPRAV1_PORTFOLIO_SECTION_COL = 11  # K «Раздел КП для Свода депо» → листы ДОМ ИА / …

# Лист 2 справочника (legacy Справочник2 — 3 колонки)
SPRAV2_ROW_START = 2
SPRAV2_COL_END = 3


def predsvod_row_to_registry(row: tuple) -> dict[str, str | None]:
    """
    Семантический маппинг predsvod col_01..col_24 → поля editable_registry.
    Индексы 0-based по col_01 = A «№ закладной (портфель)», col_05 = E «Счет депo».
    """
    def g(i: int) -> str | None:
        if i >= len(row):
            return None
        v = row[i]
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    return {
        "n_zakladnoy": g(0),
        "depository": g(2),
        "owner": g(3),
        "schet_depo": g(4),
        "razdel_scheta": g(5),
        "data_priema": g(6),
        "quantity": g(7),
        "fio": g(8),
        "nomer_kd": g(9),
        "ngri_v_depo": g(10),
        "ngri_v_portfele": g(11),
        "enc": g(12),
        "vremennoe_snyatie": g(14),
        "agent_soprovozhdeniya": g(15),
        "pul_zakladnyh": None,
        "gorod_hraneniya": g(17),
        "comment": g(21),
        "massiv_po_n": g(20),
        "massiv_po_ngri": g(22),
        "master_date": None,
        "investor": g(16),
        "servisny_agent": g(15),
        "status_eis": g(13),
        "data_pogasheniya_eis": g(18),
        "status_hraneniya": g(14),
        "hranitel": g(20),
    }

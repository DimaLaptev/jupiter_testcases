"""Проставление № закладной и ENC по НГРИ на все строки файла."""

from __future__ import annotations

from models import DayQuantityRow


def _ngri_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def fill_zakladnoy_and_enc_by_ngri(rows: list[DayQuantityRow]) -> list[DayQuantityRow]:
    """Если по НГРИ найден № закладной / ENC — заполнить пустые ячейки у всех строк."""
    zakladnoy_by_ngri: dict[str, str] = {}
    enc_by_ngri: dict[str, str] = {}

    for row in rows:
        key = _ngri_key(row.ngri)
        if not key:
            continue
        if row.n_zakladnoy and str(row.n_zakladnoy).strip():
            zakladnoy_by_ngri.setdefault(key, str(row.n_zakladnoy).strip())
        if row.enc and str(row.enc).strip():
            enc_by_ngri.setdefault(key, str(row.enc).strip())

    for row in rows:
        key = _ngri_key(row.ngri)
        if not key:
            continue
        if (not row.n_zakladnoy or not str(row.n_zakladnoy).strip()) and key in zakladnoy_by_ngri:
            row.n_zakladnoy = zakladnoy_by_ngri[key]
        if (not row.enc or not str(row.enc).strip()) and key in enc_by_ngri:
            row.enc = enc_by_ngri[key]

    return rows

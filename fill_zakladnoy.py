"""Проставление № закладной и ENC по НГРИ на все строки файла."""

from __future__ import annotations

from models import DayQuantityRow, SvodDepoRow


def _ngri_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _nonempty(value: object | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def fill_zakladnoy_and_enc_by_ngri(
    rows: list[DayQuantityRow],
    curr_svod: list[SvodDepoRow] | None = None,
) -> list[DayQuantityRow]:
    """
    Пустые № закладной / ENC заполнить по НГРИ.

    Сначала текущий СВОД (блок «на конец месяца»), затем уже собранные строки выхода.
    """
    zakladnoy_by_ngri: dict[str, str] = {}
    enc_by_ngri: dict[str, str] = {}

    for svod in curr_svod or []:
        key = _ngri_key(svod.ngri)
        if not key:
            continue
        n = _nonempty(svod.n_zakladnoy)
        e = _nonempty(svod.enc)
        if n:
            zakladnoy_by_ngri.setdefault(key, n)
        if e:
            enc_by_ngri.setdefault(key, e)

    for row in rows:
        key = _ngri_key(row.ngri)
        if not key:
            continue
        n = _nonempty(row.n_zakladnoy)
        e = _nonempty(row.enc)
        if n:
            zakladnoy_by_ngri.setdefault(key, n)
        if e:
            enc_by_ngri.setdefault(key, e)

    for row in rows:
        key = _ngri_key(row.ngri)
        if not key:
            continue
        if not _nonempty(row.n_zakladnoy) and key in zakladnoy_by_ngri:
            row.n_zakladnoy = zakladnoy_by_ngri[key]
        if not _nonempty(row.enc) and key in enc_by_ngri:
            row.enc = enc_by_ngri[key]

    return rows

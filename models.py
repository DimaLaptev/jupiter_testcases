"""Модели данных Day_Quantity pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class FlowDirection(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


ABSENT = "отсутствует"


@dataclass
class SvodDepoRow:
    """Строка СВОД_поДЕПО (нужные поля для Day_Quantity)."""

    ngri: str
    n_zakladnoy: str | None
    enc: str | None
    schet_depo: str
    razdel_scheta: str
    sheet_name: str | None = None
    source_file: str | None = None

    def path_key(self) -> tuple[str, str, str]:
        return (
            (self.ngri or "").strip().casefold(),
            (self.schet_depo or "").strip().casefold(),
            (self.razdel_scheta or "").strip().casefold(),
        )


@dataclass
class OrdOpRow:
    """Строка поручения из Ord_Quantity / СВОД_операций."""

    ngri: str
    schet_depo: str
    razdel_scheta: str
    instruction_type: str
    op_date: date | None
    op_date_raw: str | None = None
    op_type: str | None = None
    direction: FlowDirection | None = None

    def path_key(self) -> tuple[str, str, str]:
        return (
            (self.ngri or "").strip().casefold(),
            (self.schet_depo or "").strip().casefold(),
            (self.razdel_scheta or "").strip().casefold(),
        )


@dataclass
class DayQuantityRow:
    """Строка выходного Day_Quantity (колонки A–O)."""

    ngri: str | None = None
    n_zakladnoy: str | None = None
    enc: str | None = None
    schet_depo: str | None = None
    razdel_scheta: str | None = None
    start_ngri: str | None = None
    start_schet: str | None = None
    start_razdel: str | None = None
    end_ngri: str | None = None
    end_schet: str | None = None
    end_razdel: str | None = None
    instruction_type: str | None = None
    instruction_date: str | None = None
    storage_days: int | None = None
    comment: str | None = None

    def as_tuple(self) -> tuple[object, ...]:
        return (
            self.ngri,
            self.n_zakladnoy,
            self.enc,
            self.schet_depo,
            self.razdel_scheta,
            self.start_ngri,
            self.start_schet,
            self.start_razdel,
            self.end_ngri,
            self.end_schet,
            self.end_razdel,
            self.instruction_type,
            self.instruction_date,
            self.storage_days,
            self.comment,
        )


DAY_HEADERS: tuple[str, ...] = (
    "НГРИ",
    "№ закладной",
    "Признак ENC",
    "Счет депо",
    "Раздел счета депо",
    "НГРИ",
    "Счет депо",
    "Раздел счета депо",
    "НГРИ",
    "Счет депо",
    "Раздел счета депо",
    "Тип поручения",
    "Дата поручения",
    "Количество дней хранения",
    "Комментарий",
)

DAY_GROUP_HEADERS: tuple[str | None, ...] = (
    None,
    None,
    None,
    None,
    None,
    "На начало месяца",
    None,
    None,
    "На конец месяца",
    None,
    None,
    None,
    None,
    None,
    None,
)

ORD_SHEET_NAME = "СВОД_операций"

SVOD_COL_ALIASES: dict[str, tuple[str, ...]] = {
    "ngri": ("НГРИ в депо", "НГРИ"),
    "n_zakladnoy": ("Номер закладной в портфеле", "№ закладной", "Номер закладной"),
    "enc": ("ENC", "Признак ENC"),
    "schet_depo": ("Счет депо", "Счёт депо"),
    "razdel_scheta": ("Раздел счета депо", "Раздел счёта депо", "Раздел депо"),
}

ORD_COL_ALIASES: dict[str, tuple[str, ...]] = {
    "ngri": ("НГРИ",),
    "schet_depo": ("Счет депо", "Счёт депо"),
    "razdel_scheta": ("Раздел депо", "Раздел счета депо", "Раздел счёта депо"),
    "instruction_type": ("Тип поручения",),
    "op_type": ("Тип операции",),
    "op_date": ("Дата операции", "Дата поручения"),
}

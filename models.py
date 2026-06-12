"""Модели данных pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SourceKind(str, Enum):
    GPB = "GPB"
    RSD_MSG = "RSD_MSG"
    RSD_XLS = "RSD_xls"
    REGION = "REGION"
    VTBSD = "VTBSD"


class OutputSheet(str, Enum):
    GPB = "GPB"
    RSD_MSG = "RSD_MSG"
    REGION = "REGION"
    VTBSD = "VTBSD"


SOURCE_TO_SHEET: dict[SourceKind, OutputSheet] = {
    SourceKind.GPB: OutputSheet.GPB,
    SourceKind.RSD_MSG: OutputSheet.RSD_MSG,
    SourceKind.RSD_XLS: OutputSheet.RSD_MSG,
    SourceKind.REGION: OutputSheet.REGION,
    SourceKind.VTBSD: OutputSheet.VTBSD,
}


@dataclass
class DepoReportRow:
    """Строка депозитарного отчёта (ДО)."""

    source_kind: SourceKind
    source_file: str
    schet_depo: str
    razdel_scheta: str
    ngri_v_depo: str
    status: str | None = None
    data_priema: str | None = None
    fio: str | None = None
    nomer_kd: str | None = None
    section_text: str | None = None  # ВТБ: полный текст раздела для кодификатора


@dataclass
class DepoDomRecord:
    """Строка DEPO_DOM (свод за пред. месяц)."""

    portfolio_no: str | None
    dom_no: str | None
    fio: str | None
    nomer_kd: str | None
    ngri_v_depo: str | None
    data_pogasheniya: str | None
    mos_nz: str | None
    comment: str | None
    kadastr: str | None
    address: str | None


@dataclass
class Sprav1Record:
    depository: str | None
    owner: str | None
    servisny_agent: str | None
    sdelka_ia: str | None
    enc: str | None
    vid_ucheta: str | None


@dataclass
class SvodRow:
    """Строка выходного свода (колонки A–AA)."""

    n_zakladnoy_portfel: str | None = None
    n_zakladnoy_dom: str | None = None
    depository: str | None = None
    owner: str | None = None
    schet_depo: str | None = None
    razdel_scheta: str | None = None
    data_priema: str | None = None
    quantity: str | None = "1"
    fio: str | None = None
    nomer_kd: str | None = None
    ngri_v_depo: str | None = None
    ngri_v_portfele: str | None = None
    enc: str | None = None
    vid_ucheta: str | None = None
    sostoyanie: str | None = None
    servisny_agent: str | None = None
    sdelka_ia: str | None = None
    gorod_hraneniya: str | None = None
    data_pogasheniya: str | None = None
    mos_nz: str | None = None
    mestonahozhdenie: str | None = None
    comment: str | None = None
    kadastr: str | None = None
    address: str | None = None
    istochnik: str | None = None
    sravnenie: str | None = None

    def as_tuple(self) -> tuple[str | None, ...]:
        return (
            self.n_zakladnoy_portfel,
            self.n_zakladnoy_dom,
            self.depository,
            self.owner,
            self.schet_depo,
            self.razdel_scheta,
            self.data_priema,
            self.quantity,
            self.fio,
            self.nomer_kd,
            self.ngri_v_depo,
            self.ngri_v_portfele,
            self.enc,
            self.vid_ucheta,
            None,  # O — не используется в новой спецификации
            self.sostoyanie,
            self.servisny_agent,
            self.sdelka_ia,
            self.gorod_hraneniya,
            self.data_pogasheniya,
            self.mos_nz,
            self.mestonahozhdenie,
            self.comment,
            self.kadastr,
            self.address,
            self.istochnik,
            self.sravnenie,
        )


SVOD_HEADERS: tuple[str, ...] = (
    "Номер закладной в портфеле",
    "Номер закладной ДОМа",
    "Депозитарий",
    "Владелец",
    "Счет депо",
    "Раздел счета депо",
    "Дата приема на ДУ",
    "Количество",
    "ФИО заемщика",
    "Номер КД",
    "НГРИ в депо",
    "НГРИ в портфеле",
    "ENC",
    "Вид учета",
    "",  # O
    "Состояние",
    "Сервисный агент",
    "Сделка ИА",
    "Город хранения",
    "Дата погашения",
    "МОС НЗ",
    "Местонахождение",
    "Комментарий",
    "Кадастровый номер",
    "Адрес",
    "Источник",
    "Сравнение",
)

DEPO_DOM_SHEETS = ("GPB", "RSD_MSG", "REGION", "VTBSD")

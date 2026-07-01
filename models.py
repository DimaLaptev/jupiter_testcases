"""Модели данных pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceKind(str, Enum):
    GPB = "GPB"
    RSD_MSG = "RSD_MSG"
    RSD_R05 = "RSD_R05"
    RSD_XLS = "RSD_xls"  # alias для совместимости
    REGION = "REGION"
    VTBSD = "VTBSD"


class DepoDomSheet(str, Enum):
    """Листы DEPO_DOM для lookup по источнику."""

    GPB = "GPB"
    RSD_MSG = "RSD_MSG"
    REGION = "REGION"
    VTBSD = "VTBSD"


SOURCE_TO_DEPO_DOM_SHEET: dict[SourceKind, DepoDomSheet] = {
    SourceKind.GPB: DepoDomSheet.GPB,
    SourceKind.RSD_MSG: DepoDomSheet.RSD_MSG,
    SourceKind.RSD_R05: DepoDomSheet.RSD_MSG,
    SourceKind.RSD_XLS: DepoDomSheet.RSD_MSG,
    SourceKind.REGION: DepoDomSheet.REGION,
    SourceKind.VTBSD: DepoDomSheet.VTBSD,
}

PORTFOLIO_SHEET_DOM_IA = "ДОМ ИА"
PORTFOLIO_SHEET_VTB = "ДОМ ИА-Оригинатор ВТБ"
PORTFOLIO_SHEET_SBER = "ДОМ ИА-Оригинатор Сбер"
PORTFOLIO_SHEET_REZERVIS = "ДОМ_Оригинатор ДОМ_РезСервис"

SVOD_IA_SHEETS: tuple[str, ...] = (
    PORTFOLIO_SHEET_DOM_IA,
    PORTFOLIO_SHEET_VTB,
    PORTFOLIO_SHEET_SBER,
)
SVOD_DOM_SHEETS: tuple[str, ...] = (PORTFOLIO_SHEET_REZERVIS,)

ALL_PORTFOLIO_SHEETS: tuple[str, ...] = SVOD_IA_SHEETS + SVOD_DOM_SHEETS

PORTFOLIO_TO_WORKBOOK: dict[str, str] = {
    PORTFOLIO_SHEET_DOM_IA: "svod",
    PORTFOLIO_SHEET_VTB: "svod",
    PORTFOLIO_SHEET_SBER: "svod",
    PORTFOLIO_SHEET_REZERVIS: "svod_dom",
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
    portfolio_section: str | None = None


@dataclass
class SvodRow:
    """Строка выходного свода (колонки A–Z)."""

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
DEPO_IA_SHEETS = ("GPB", "REGION", "VTBSD", "RSD_XLS")

SOURCE_TO_DEPO_IA_SHEET: dict[SourceKind, str] = {
    SourceKind.GPB: "GPB",
    SourceKind.RSD_MSG: "RSD_XLS",
    SourceKind.RSD_R05: "RSD_XLS",
    SourceKind.RSD_XLS: "RSD_XLS",
    SourceKind.REGION: "REGION",
    SourceKind.VTBSD: "VTBSD",
}

"""Константы и реестр шагов фазы depo (svod_depo)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DepoStepKind(str, Enum):
    IMPORT = "import"
    EXPORT = "export"
    CHECK = "check"
    PROCEDURE = "procedure"
    FORM = "form"


@dataclass(frozen=True)
class DepoStepDef:
    name: str
    kind: DepoStepKind
    sheet_name: str | None = None
    portfolio_section: str | None = None
    sql: str | None = None
    add_sheet_name: str | None = None


# Заголовки как в VBA CopyFromRecordset (my_table.txt).
SBOR_REESTRA_HEADERS: tuple[str, ...] = (
    "№_закладной",
    "Депозитарий",
    "Владелец",
    "Счет депо",
    "Раздел счета",
    "Количество",
    "ФИО",
    "Номер КД",
    "НГРИ в депо",
    "НГРИ в портфеле",
    "Временное снятие",
    "ENC",
    "Агент по сопровождению",
    "Пул закладных",
    "Город - место хранения",
    "Комментарий",
    "массив по №",
    "массив по НГРИ",
    "Мастер на __.__.2024",
    "Инвестор",
    "Сервисный агент",
    "Статус в ЕИС на __.__.2024",
    "Дата погашения в ЕИС",
    "Статус по хранению",
    "Хранитель",
    "Дата приема",
    "Счет депо2",
    "Раздел",
    "Номер КД2",
    "Сверка с дефолтами",
    "(совпад)",
)

PROVERKA_ZAGRUZKI_HEADERS: tuple[str, ...] = (
    "Основной номер счета/ регистра (текст)",
    "Количество",
    "Депозитарий",
)

DUBLI_NGRI_HEADERS: tuple[str, ...] = (
    "НГРИ в депо",
    "Дубликат",
)

DUBLI_ZAKLADNYE_HEADERS: tuple[str, ...] = (
    "№_закладной",
    "Дубликат",
)

ADD_NEW_SHEET = "Добавление новых"
ADD_NEW_ROW_START = 5
ADD_NEW_COLS = 8

DEFAULT_DEPO_PIPELINE_ORDER: list[str] = [
    "depo_add_new",
    "depo_export_dom_ia",
    "depo_export_vtb",
    "depo_export_sber",
    "depo_export_rezervis",
    "depo_check_upload",
    "depo_check_ngri",
    "depo_check_mortgage",
    "depo_archive",
]

DEPO_STEPS: dict[str, DepoStepDef] = {
    "depo_add_new": DepoStepDef(
        name="depo_add_new",
        kind=DepoStepKind.IMPORT,
        add_sheet_name=ADD_NEW_SHEET,
    ),
    "depo_export_dom_ia": DepoStepDef(
        name="depo_export_dom_ia",
        kind=DepoStepKind.EXPORT,
        sheet_name="ДОМ ИА",
        portfolio_section="ДОМ ИА",
    ),
    "depo_export_vtb": DepoStepDef(
        name="depo_export_vtb",
        kind=DepoStepKind.EXPORT,
        sheet_name="ДОМ ИА-Оригинатор ВТБ",
        portfolio_section="ДОМ ИА-Оригинатор ВТБ",
    ),
    "depo_export_sber": DepoStepDef(
        name="depo_export_sber",
        kind=DepoStepKind.EXPORT,
        sheet_name="ДОМ ИА-Оригинатор Сбер",
        portfolio_section="ДОМ ИА-Оригинатор Сбер",
    ),
    "depo_export_rezervis": DepoStepDef(
        name="depo_export_rezervis",
        kind=DepoStepKind.EXPORT,
        sheet_name="ДОМ_Оригинатор ДОМ_РезСервис",
        portfolio_section="ДОМ_Оригинатор ДОМ_РезСервис",
    ),
    "depo_check_upload": DepoStepDef(
        name="depo_check_upload",
        kind=DepoStepKind.CHECK,
        sheet_name="проверка_загрузки",
        sql="SELECT * FROM v_proverka_zagruzki",
    ),
    "depo_check_ngri": DepoStepDef(
        name="depo_check_ngri",
        kind=DepoStepKind.CHECK,
        sheet_name="дубль_НГРИ",
        sql="SELECT * FROM v_dubli_ngri",
    ),
    "depo_check_mortgage": DepoStepDef(
        name="depo_check_mortgage",
        kind=DepoStepKind.CHECK,
        sheet_name="дубль_закладные",
        sql="SELECT * FROM v_dubli_zakladnye",
    ),
    "depo_archive": DepoStepDef(
        name="depo_archive",
        kind=DepoStepKind.PROCEDURE,
    ),
    "depo_form_update": DepoStepDef(
        name="depo_form_update",
        kind=DepoStepKind.FORM,
    ),
}


def get_depo_step(name: str) -> DepoStepDef:
    if name not in DEPO_STEPS:
        raise KeyError(f"Неизвестный depo-шаг: {name}")
    return DEPO_STEPS[name]

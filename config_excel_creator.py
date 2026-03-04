from openpyxl import Workbook


def create_file_handler_config_xlsx(filename: str = "file_handler_config.xlsx") -> None:
    """
    Создаёт excel-файл с настройками по Таблице №1 и №2 (tz/Sprav_p_1_3).
    Коды хранятся как текст (формат @), чтобы сохранить ведущие нули.
    """

    wb = Workbook()
    ws = wb.active
    ws.title = "config"

    # Шапка
    ws.append(["section", "key", "value"])

    # Базовые директории
    ws.append(["base", "SOURCE_DIR", "./0_DECODE/"])
    ws.append(["base", "DIR_DOMRF", "DOMRF"])
    ws.append(["base", "DIR_DOMRFIA", "DOMRFIA"])

    def add_list(section: str, key: str, values: list, as_text: bool = False) -> None:
        """Добавляет строки. as_text=True — значение в формате текст (для кодов с ведущими нулями)."""
        start_row = ws.max_row + 1
        for v in values:
            ws.append([section, key, str(v)])
        if as_text:
            for r in range(start_row, ws.max_row + 1):
                ws.cell(row=r, column=3).number_format = "@"

    # Таблица №1 — DOMRF
    add_list("patterns", "pattern_DOMRF_MSG", [".MSG"])
    add_list(
        "patterns",
        "pattern_DOMRF_MSG_code",
        [
            "00070",
            "00107",
            "00108",
            "00109",
            "00110",
            "00124",
            "00133",
            "00135",
            "00166",
            "00167",
            "00170",
            "00221",
            "00222",
            "00248",
            "00252",
            "00004",
            "00036",
            "00083",
        ],
        as_text=True,
    )

    add_list("patterns", "pattern_DOMRF_any", [".xls", ".pdf", ".zip"])
    add_list(
        "patterns",
        "pattern_DOMRF_any_code",
        [
            "10934",
            "26716",
            "26724",
            "26732",
            "26740",
            "28142",
            "33563",
            "33597",
            "30510",
            "30502",
        ],
        as_text=True,
    )

    add_list("patterns", "pattern_DOMRF_TXT", [".txt"])
    add_list("patterns", "pattern_DOMRF_TXT_code", ["778", "3194"], as_text=True)

    # Таблица №2 — DOMRFIA
    add_list("patterns", "pattern_DOMRFIA_MSG", [".MSG"])
    add_list(
        "patterns",
        "pattern_DOMRFIA_MSG_code",
        [
            "00226",
            "00227",
            "00234",
            "00235",
            "00239",
            "00240",
            "00253",
            "00254",
            "00255",
            "00256",
            "00263",
            "00264",
        ],
        as_text=True,
    )

    add_list("patterns", "pattern_DOMRFIA_any", [".xls", ".pdf", ".zip"])
    add_list(
        "patterns",
        "pattern_DOMRFIA_any_code",
        [
            "33514",
            "33506",
            "33639",
            "33613",
            "33647",
            "33621",
            "33753",
            "33761",
            "33472",
            "33480",
        ],
        as_text=True,
    )

    wb.save(filename)


if __name__ == "__main__":
    create_file_handler_config_xlsx()

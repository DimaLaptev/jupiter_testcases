from openpyxl import Workbook


def create_file_handler_config_xlsx(filename: str = "file_handler_config.xlsx") -> None:
    """
    Создаёт excel-файл (Excel) с настройками, эквивалентными
    текущим хардкодам в file_handler.py.
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

    # Паттерны и коды — каждая запись отдельной строкой
    def add_list(section: str, key: str, values):
        for v in values:
            ws.append([section, key, v])

    # DOMRF
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
            "00161",
            "00176",
            "00182",
            "00209",
            "00228",
            "00249",
            "00252",
            "00300",
            "00306",
            "00383",
        ],
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
    )

    add_list("patterns", "pattern_DOMRF_TXT", [".txt"])
    add_list("patterns", "pattern_DOMRF_TXT_code", ["778", "3194"])

    # DOMRFIA
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
            "00250",
            "00254",
            "00255",
            "00256",
            "00264",
        ],
    )

    add_list("patterns", "pattern_DOMRFIA_any", [".xls", ".pdf", ".zip"])
    add_list(
        "patterns",
        "pattern_DOMRFIA_any_code",
        [
            "33514",
            "33566",
            "33569",
            "33639",
            "33670",
            "33621",
            "33576",
            "33579",
            "33472",
            "33480",
        ],
    )

    wb.save(filename)


if __name__ == "__main__":
    create_file_handler_config_xlsx()

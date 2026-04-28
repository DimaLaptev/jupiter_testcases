"""Юнит-тесты (unit tests) REGION: имя файла и разбор шапки по колонке C."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from region_is_xls import (  # noqa: E402
    RegionParseResult,
    RegionTableRow,
    _parse_region_header_accounts_c,
    parse_region_filename_stem,
)
from codifier_table import CodifierRow  # noqa: E402
from svod_excel import (  # noqa: E402
    REGION_ERROR_ACCOUNT_MISMATCH,
    build_svod_row_region,
)


class TestParseRegionFilenameStem(unittest.TestCase):
    def test_four_parts(self) -> None:
        a, t = parse_region_filename_stem("IS25020720980_VH25020737840_VL0089_Прием ЦБ - перевод")
        self.assertEqual(a, "VL0089")
        self.assertEqual(t, "Прием ЦБ - перевод")

    def test_extra_underscores_in_title(self) -> None:
        a, t = parse_region_filename_stem("IS1_VH2_V99_One_Two")
        self.assertEqual(a, "V99")
        self.assertEqual(t, "One_Two")

    def test_too_few_parts(self) -> None:
        self.assertEqual(parse_region_filename_stem("ISONLY"), ("", ""))


class TestParseRegionHeaderAccountsC(unittest.TestCase):
    def test_sections_before_and_after_so_scheta(self) -> None:
        rows = [
            ["на счет депо", "", "VL0089"],
            ["", "", ""],
            ["Наименование раздела счета депо", "", "Раздел зачисления"],
            ["со счета депо", "", "VL0100"],
            ["Наименование раздела счета депо", "", "Раздел списания"],
        ]
        fa, fsec, ta, tsec = _parse_region_header_accounts_c(rows)
        self.assertEqual(ta, "VL0089")
        self.assertEqual(fa, "VL0100")
        self.assertEqual(tsec, "Раздел зачисления")
        self.assertEqual(fsec, "Раздел списания")


class TestBuildSvodRowRegion(unittest.TestCase):
    def test_account_mismatch_is_error_only(self) -> None:
        pr = RegionParseResult(
            path=Path("IS_PREF_VH_SEG_VL001_Operation.XLS"),
            operation_type="",
            op_date="01.02.2025",
            from_acc="AAA",
            from_sec="Sa",
            to_acc="BBB",
            to_sec="Sb",
            basis="",
            reg_footer="",
            filename_account="VL001",
            filename_operation_title="Operation",
            table_rows=[],
        )
        tr = RegionTableRow(ngri="4719000000004719")
        svod, err = build_svod_row_region(pr, tr, [], [])
        self.assertIsNone(svod)
        self.assertIsNotNone(err)
        self.assertEqual(err[3], REGION_ERROR_ACCOUNT_MISMATCH)

    def test_match_to_writes_svod(self) -> None:
        pr = RegionParseResult(
            path=Path("IS_PREF_VH_SEG_VV88_Operation.XLS"),
            operation_type="",
            op_date="01.02.2025",
            from_acc="AAA",
            from_sec="Sa",
            to_acc="VV88",
            to_sec="Sb",
            basis="",
            reg_footer="",
            filename_account="VV88",
            filename_operation_title="Operation",
            table_rows=[],
        )
        tr = RegionTableRow(ngri="")
        cr = CodifierRow(
            op_code="101",
            exec_code="",
            op_type="Тип регион",
            content_gpb="",
            instruction_type="T",
            comment="",
            content_region="Operation",
            content_rsd="",
        )
        svod, err = build_svod_row_region(pr, tr, [], [cr])
        self.assertIsNotNone(svod)
        self.assertIsNone(err)
        self.assertEqual(svod[5], "VV88")  # F Счет депо = matched side зачисления


if __name__ == "__main__":
    unittest.main()

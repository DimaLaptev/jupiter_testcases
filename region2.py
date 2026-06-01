"""Загрузчик Регион2 (VBA Sub Регион2) → region2_temp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.registry import register_loader
from sql_upload.values import cell_to_sql_value

REGION2_HEADERS = (
    "/ReportHeader/DepoAccount/DepoAccount",
    "/ReportBody/PositionList/Position/DivisionList/Division/DivisionInfo/DivisionName",
    "/ReportBody/PositionList/Position/DivisionList/Division/Quantity",
    "/ReportBody/PositionList/Position/PositionInfo/Mortgage/AgreementNumber",
    "/ReportBody/PositionList/Position/PositionInfo/Mortgage/RegistrationNumber",
)


def _match_header_columns(header_row: list[str]) -> list[int] | None:
    indices: list[int] = []
    for header in REGION2_HEADERS:
        try:
            idx = header_row.index(header)
        except ValueError:
            return None
        indices.append(idx)
    return indices


@register_loader("region2")
class Region2Loader:
    name = "region2"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="region2",
            temp_table="region2_temp",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        for _sheet_name, sheet_rows in read_workbook_sheets(path):
            a1 = cell_at(sheet_rows, 1, 1)
            a2 = cell_at(sheet_rows, 2, 1)
            if a1 != "/DEPOACCOUNT_BALANCE_REPORT" and a2 != "/ReportBody/OperationInfo/Date":
                continue
            if len(sheet_rows) < 2:
                continue
            header_row = sheet_rows[1]
            col_indices = _match_header_columns(header_row)
            if col_indices is None:
                continue
            last_row = last_row_in_column(sheet_rows, 1)
            for r in range(3, last_row + 1):
                if r - 1 >= len(sheet_rows):
                    break
                row = sheet_rows[r - 1]
                values = []
                empty = True
                for idx in col_indices:
                    val = row[idx] if idx < len(row) else ""
                    if (val or "").strip():
                        empty = False
                    values.append(cell_to_sql_value(val))
                if empty:
                    continue
                yield tuple(values)

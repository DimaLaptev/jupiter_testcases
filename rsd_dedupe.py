"""Удаление дубликатов строк РСД."""

from __future__ import annotations

from models import DepoReportRow, SourceKind

_RSD_KINDS = frozenset(
    {
        SourceKind.RSD_MSG,
        SourceKind.RSD_R05,
        SourceKind.RSD_XLS,
    },
)


def _rsd_row_key(row: DepoReportRow) -> tuple[str, str, str, str]:
    return (
        (row.schet_depo or "").strip().casefold(),
        (row.ngri_v_depo or "").strip().casefold(),
        row.source_kind.value,
        (row.source_file or "").strip().casefold(),
    )


def dedupe_rsd_do_rows(rows: list[DepoReportRow]) -> list[DepoReportRow]:
    """Оставить первое вхождение по (schet_depo, ngri, source_kind, source_file)."""
    seen: set[tuple[str, str, str, str]] = set()
    out: list[DepoReportRow] = []
    for row in rows:
        if row.source_kind not in _RSD_KINDS:
            out.append(row)
            continue
        key = _rsd_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out

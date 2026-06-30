"""Матрица источников по депозитариям."""

from __future__ import annotations

from models import SourceKind


def use_depo_dom_portfolio(source: SourceKind) -> bool:
    return source in (
        SourceKind.GPB,
        SourceKind.RSD_MSG,
        SourceKind.RSD_R05,
        SourceKind.RSD_XLS,
        SourceKind.REGION,
        SourceKind.VTBSD,
    )


def fio_from_do(source: SourceKind) -> bool:
    return source == SourceKind.VTBSD


def kd_from_do(source: SourceKind) -> bool:
    return source in (SourceKind.REGION, SourceKind.VTBSD)


def status_from_do(source: SourceKind) -> bool:
    return source in (SourceKind.GPB, SourceKind.REGION)


def status_constant(source: SourceKind) -> str | None:
    if source in (SourceKind.RSD_MSG, SourceKind.RSD_R05, SourceKind.RSD_XLS):
        return "На хранении"
    return None


def use_vtb_codifier(source: SourceKind) -> bool:
    return source == SourceKind.VTBSD


def data_priema_from_do(source: SourceKind) -> bool:
    return source in (
        SourceKind.RSD_MSG,
        SourceKind.RSD_R05,
        SourceKind.RSD_XLS,
        SourceKind.REGION,
        SourceKind.VTBSD,
    )

"""Кодификатор ВТБ СД: раздел счета депo → P/M/N."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VtbCodifierResult:
    sostoyanie: str
    enc: str
    vid_ucheta: str


_ELECTRONIC = "(электронное хранилище)"


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def lookup_vtb_section(section_text: str | None) -> VtbCodifierResult:
    text = section_text or ""
    n = _norm(text)
    electronic = _ELECTRONIC in n

    if "закладные обездвижены" in n and "включены в рип" in n:
        return VtbCodifierResult("На хранении", "ENC2", "Депозитарный учет ДЗ")

    if "временное изъятие закладных" in n and not electronic:
        return VtbCodifierResult("Временное снятие ДЗ", "ENC2", "Депозитарный учет ДЗ")

    if "блокировано до выпуска" in n and electronic:
        return VtbCodifierResult("Временное снятие ЭЗ", "ENC3", "Депозитарный учет ЭЗ")

    if "электронные закладные" in n and "включены в рип" in n:
        return VtbCodifierResult("На хранении", "ENC3", "Депозитарный учет ЭЗ")

    if "свободное обращение" in n:
        if electronic:
            return VtbCodifierResult("На хранении", "ENC3", "Депозитарный учет ЭЗ")
        return VtbCodifierResult("На хранении", "ENC2", "Депозитарный учет ДЗ")

    if electronic:
        return VtbCodifierResult("На хранении", "ENC3", "Депозитарный учет ЭЗ")

    return VtbCodifierResult("На хранении", "ENC2", "Депозитарный учет ДЗ")

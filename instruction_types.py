"""Типы поручений: зачисление (credit) / списание (debit)."""

from __future__ import annotations

from models import FlowDirection

# Фильтр строк Ord_Quantity для Day_Quantity
INSTRUCTION_TYPES: frozenset[str] = frozenset(
    {"Z", "G", "P", "F", "XP", "XF", "RP", "RF", "VP", "VF"},
)

CREDIT_TYPES: frozenset[str] = frozenset({"Z", "F", "XF", "RF", "VF"})
DEBIT_TYPES: frozenset[str] = frozenset({"G", "P", "XP", "RP", "VP"})

INSTRUCTION_DIRECTION: dict[str, FlowDirection] = {
    **{t: FlowDirection.CREDIT for t in CREDIT_TYPES},
    **{t: FlowDirection.DEBIT for t in DEBIT_TYPES},
}


def normalize_instruction_type(value: object | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    return s or None


def direction_for(instruction_type: str | None) -> FlowDirection | None:
    if not instruction_type:
        return None
    return INSTRUCTION_DIRECTION.get(instruction_type.strip().upper())


def is_tracked_instruction(instruction_type: str | None) -> bool:
    if not instruction_type:
        return False
    return instruction_type.strip().upper() in INSTRUCTION_TYPES

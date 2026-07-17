"""Типы поручений: зачисление (credit) / списание (debit)."""

from __future__ import annotations

import re

from models import FlowDirection

# Фильтр строк Ord_Quantity для Day_Quantity
INSTRUCTION_TYPES: frozenset[str] = frozenset(
    {"Z", "G", "P", "F", "XP", "XF", "RP", "RF", "VP", "VF", "E"},
)

CREDIT_TYPES: frozenset[str] = frozenset({"Z", "F", "XF", "RF", "VF"})
DEBIT_TYPES: frozenset[str] = frozenset({"G", "P", "XP", "RP", "VP"})
# E: направление только из «Тип операции»
OP_TYPE_DIRECTION_TYPES: frozenset[str] = frozenset({"E"})

INSTRUCTION_DIRECTION: dict[str, FlowDirection] = {
    **{t: FlowDirection.CREDIT for t in CREDIT_TYPES},
    **{t: FlowDirection.DEBIT for t in DEBIT_TYPES},
}

# Конец «Тип операции»: «… - зачисление» / «… - списание» (также «снятие»)
_OP_TYPE_FLOW_RE = re.compile(
    r"(?:-|–|—)\s*(списание|снятие|зачисление)\s*$",
    re.IGNORECASE,
)


def normalize_instruction_type(value: object | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    return s or None


def direction_from_op_type(op_type: object | None) -> FlowDirection | None:
    """Направление по хвосту «Тип операции» (зачисление / списание|снятие)."""
    if op_type is None:
        return None
    text = str(op_type).strip()
    if not text:
        return None
    m = _OP_TYPE_FLOW_RE.search(text)
    if not m:
        # fallback: последнее слово
        folded = text.casefold()
        if folded.endswith("зачисление"):
            return FlowDirection.CREDIT
        if folded.endswith("списание") or folded.endswith("снятие"):
            return FlowDirection.DEBIT
        return None
    word = m.group(1).casefold()
    if word == "зачисление":
        return FlowDirection.CREDIT
    return FlowDirection.DEBIT


def direction_for(
    instruction_type: str | None,
    *,
    op_type: object | None = None,
) -> FlowDirection | None:
    """Направление: для E — из «Тип операции», иначе по коду поручения."""
    if not instruction_type:
        return None
    code = instruction_type.strip().upper()
    if code in OP_TYPE_DIRECTION_TYPES:
        return direction_from_op_type(op_type)
    return INSTRUCTION_DIRECTION.get(code)


def is_tracked_instruction(instruction_type: str | None) -> bool:
    if not instruction_type:
        return False
    return instruction_type.strip().upper() in INSTRUCTION_TYPES

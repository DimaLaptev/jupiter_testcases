"""
Таблица соответствия «Код выписки ГПБ (ДОМ)» -> «Номер счета депо».
колонка H -> колонка C.
"""

from typing import Optional

# Код выписки ГПБ (ДОМ) -> Номер счета депо
# ClientID сопоставляется с кодом выписки (привести к int для поиска)
GPB_CODE_TO_DEPO_ACCOUNT = {
    4: 778,
    83: 3194,
    70: 10934,
    109: 26716,
    108: 26724,
    107: 26732,
    110: 26740,
    136: 28142,
    248: 33563,
    252: 33597,
    167: 30510,
    166: 30502,
    240: 33514,
    239: 33506,
    234: 33472,
    235: 33480,
}


def get_depo_account_by_client_id(client_id: str) -> Optional[int]:
    """
    Находит «Номер счета депо» по ClientID.
    Приводит типы к int для корректного сопоставления.
    """
    try:
        code = int(client_id.strip())
    except (ValueError, AttributeError):
        return None
    return GPB_CODE_TO_DEPO_ACCOUNT.get(code)

"""Исключения клиента адаптера (adapter) RVBCN.EGRN."""


class AdapterError(Exception):
    """Базовая ошибка взаимодействия с адаптером (adapter)."""

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class AdapterTimeoutError(AdapterError):
    """Таймаут (timeout): HTTP 504 Gateway Timeout или истечение ожидания ответа."""


class AdapterUpstreamError(AdapterError):
    """Ошибка upstream (SMEV4/ПОДД): HTTP 502 или 503 + errorCode/message."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)
        self.status_code = status_code


class AdapterBatchFailedError(AdapterError):
    """Пакетный (batch) запрос завершился со status=FAILED."""


class AdapterPartialResultError(AdapterError):
    """Пакетный (batch) запрос завершился со status=PARTIAL (есть ошибки по объектам)."""

    def __init__(self, message: str, *, result: object | None = None) -> None:
        super().__init__(message)
        self.result = result

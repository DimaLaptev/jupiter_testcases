"""SQLite ETL: замена VBA-макросов загрузки в staging-таблицы."""

from sql_upload.connection import DEFAULT_DB_PATH, open_db
from sql_upload.pipeline import DEFAULT_PIPELINE_ORDER, run_pipeline

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_PIPELINE_ORDER",
    "open_db",
    "run_pipeline",
]

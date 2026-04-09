"""Планировщик (scheduler) по README: задачи только для модулей, присутствующих в репозитории."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_TZ = "Europe/Moscow"


def _run_create_folders() -> None:
    """1.1 — 2-й день месяца, 6:50 — create_folders.py."""
    try:
        from create_folders import create_folder_structure, show_folder_tree

        root = create_folder_structure()
        show_folder_tree(root)
    except Exception:
        logger.exception("create_folders: ошибка выполнения")


def _run_mail() -> None:
    """1.2 — ежедневно 7:00 — mail.py."""
    try:
        from mail import connect_and_read_email

        connect_and_read_email()
    except Exception:
        logger.exception("mail: ошибка выполнения")


def _run_file_handler() -> None:
    """1.3 — ежедневно 7:30 — file_handler.py (сортировка в DOMRF/DOMRFIA)."""
    try:
        from file_handler import sort_files_DOMRF_DOMRFIA

        sort_files_DOMRF_DOMRFIA()
    except Exception:
        logger.exception("file_handler: ошибка выполнения")


def run_scheduler() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    scheduler = BlockingScheduler(timezone=_TZ)

    # Ежемесячно: 2-й день, 6:50
    scheduler.add_job(
        _run_create_folders,
        CronTrigger(day=2, hour=6, minute=50, timezone=_TZ),
        id="create_folders_monthly",
        name="1.1 create_folders.py",
        replace_existing=True,
    )
    # Ежедневно 7:00
    scheduler.add_job(
        _run_mail,
        CronTrigger(hour=7, minute=0, timezone=_TZ),
        id="mail_daily",
        name="1.2 mail.py",
        replace_existing=True,
    )
    # Ежедневно 7:30
    scheduler.add_job(
        _run_file_handler,
        CronTrigger(hour=7, minute=30, timezone=_TZ),
        id="file_handler_daily",
        name="1.3 file_handler.py",
        replace_existing=True,
    )

    logger.info("Планировщик запущен (timezone=%s). Задачи: 1.1, 1.2, 1.3.", _TZ)
    for j in scheduler.get_jobs():
        logger.info("Зарегистрировано: %s — следующий запуск: %s", j.name, j.next_run_time)
    scheduler.start()

"""Планировщик (scheduler) по README — все шаги алгоритма 1."""

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
    """1.3 — ежедневно 7:30 — file_handler.py."""
    try:
        from file_handler import sort_files_DOMRF_DOMRFIA

        sort_files_DOMRF_DOMRFIA()
    except Exception:
        logger.exception("file_handler: ошибка выполнения")


def _run_copy_I_msg_files() -> None:
    """1.4 — ежедневно 11:00 — copy_I_msg_files.py."""
    try:
        import copy_I_msg_files as m

        m.copy_I_msg_files(m.dir_list)
    except Exception:
        logger.exception("copy_I_msg_files: ошибка выполнения")


def _run_copy_REP_xls_files() -> None:
    """1.5 — ежедневно 11:10 — copy_REP_xls_files.py."""
    try:
        from copy_REP_xls_files import copy_REP_xls_files

        copy_REP_xls_files()
    except Exception:
        logger.exception("copy_REP_xls_files: ошибка выполнения")


def _run_file_handler_2() -> None:
    """1.6 — ежедневно 11:20 — file_handler_2.py."""
    try:
        from file_handler_2 import move_files_to_dir_struct

        move_files_to_dir_struct()
    except Exception:
        logger.exception("file_handler_2: ошибка выполнения")


def _run_validate_gpb() -> None:
    """1.6.1 — ежедневно 11:30 — validate_gpb_files.py."""
    try:
        from validate_gpb_files import main as validate_gpb_main

        validate_gpb_main()
    except Exception:
        logger.exception("validate_gpb_files: ошибка выполнения")


def _run_unpack_zip() -> None:
    """1.7.1 — ежедневно 17:00 — unpack_zip.py."""
    try:
        from unpack_zip import run_unpack_zip_jobs

        run_unpack_zip_jobs()
    except Exception:
        logger.exception("unpack_zip: ошибка выполнения")


def _run_copy_I_msg_files_2() -> None:
    """1.7.2 — после распаковки; по расписанию 17:10 — copy_I_msg_files_2.py."""
    try:
        from copy_I_msg_files_2 import run_copy_I_msg_files_2_default

        run_copy_I_msg_files_2_default()
    except Exception:
        logger.exception("copy_I_msg_files_2: ошибка выполнения")


def _run_file_handler_3() -> None:
    """1.7.3 — после 1.7.2; по расписанию 17:20 — file_handler_3.py."""
    try:
        from file_handler_3 import move_files_to_dir_struct_2

        move_files_to_dir_struct_2()
    except Exception:
        logger.exception("file_handler_3: ошибка выполнения")


def _run_validate_rsd() -> None:
    """1.7.4 — после 1.7.3; по расписанию 17:30 — validate_rsd_files.py."""
    try:
        from validate_rsd_files import main as validate_rsd_main

        validate_rsd_main()
    except Exception:
        logger.exception("validate_rsd_files: ошибка выполнения")


def run_scheduler() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    scheduler = BlockingScheduler(timezone=_TZ)

    scheduler.add_job(
        _run_create_folders,
        CronTrigger(day=2, hour=6, minute=50, timezone=_TZ),
        id="create_folders_monthly",
        name="1.1 create_folders.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_mail,
        CronTrigger(hour=7, minute=0, timezone=_TZ),
        id="mail_daily",
        name="1.2 mail.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_file_handler,
        CronTrigger(hour=7, minute=30, timezone=_TZ),
        id="file_handler_daily",
        name="1.3 file_handler.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_copy_I_msg_files,
        CronTrigger(hour=11, minute=0, timezone=_TZ),
        id="copy_I_msg_files",
        name="1.4 copy_I_msg_files.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_copy_REP_xls_files,
        CronTrigger(hour=11, minute=10, timezone=_TZ),
        id="copy_REP_xls_files",
        name="1.5 copy_REP_xls_files.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_file_handler_2,
        CronTrigger(hour=11, minute=20, timezone=_TZ),
        id="file_handler_2",
        name="1.6 file_handler_2.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_validate_gpb,
        CronTrigger(hour=11, minute=30, timezone=_TZ),
        id="validate_gpb_files",
        name="1.6.1 validate_gpb_files.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_unpack_zip,
        CronTrigger(hour=17, minute=0, timezone=_TZ),
        id="unpack_zip",
        name="1.7.1 unpack_zip.py",
        replace_existing=True,
    )
    # Цепочка RSD: фиксированные слоты после 1.7.1 (README: «по завершении предыдущего»)
    scheduler.add_job(
        _run_copy_I_msg_files_2,
        CronTrigger(hour=17, minute=10, timezone=_TZ),
        id="copy_I_msg_files_2",
        name="1.7.2 copy_I_msg_files_2.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_file_handler_3,
        CronTrigger(hour=17, minute=20, timezone=_TZ),
        id="file_handler_3",
        name="1.7.3 file_handler_3.py",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_validate_rsd,
        CronTrigger(hour=17, minute=30, timezone=_TZ),
        id="validate_rsd_files",
        name="1.7.4 validate_rsd_files.py",
        replace_existing=True,
    )

    logger.info(
        "Планировщик запущен (timezone=%s). Полный алгоритм 1 (README).",
        _TZ,
    )
    for j in scheduler.get_jobs():
        next_at = getattr(j, "next_run_time", None)
        logger.info(
            "Зарегистрировано: %s (id=%s) — следующий запуск: %s",
            j.name,
            j.id,
            next_at,
        )
    scheduler.start()

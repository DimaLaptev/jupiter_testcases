# 1.2


import os
import traceback
import pytz
from datetime import datetime, timedelta

from exchangelib import (
    Credentials,
    Account,
    Configuration,
    DELEGATE,
    HTMLBody,
    Message,
    FileAttachment,
)
from exchangelib import EWSDateTime, EWSTimeZone
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter

from config_ews import (
    MAIL_1_ADDRESS,
    MAIL_1_USERNAME,
    MAIL_1_PASSWORD,
    MAIL_2_ADDRESS,
    MAIL_2_USERNAME,
    MAIL_2_PASSWORD,
    MAIL_SERVER_NAME,
    DECODE,
    REPORS_DEPO_DIRECTORY,
)

# 1.2

MAIL_CREDENTIALS = [
    [MAIL_1_ADDRESS, MAIL_1_USERNAME, MAIL_1_PASSWORD],
    [MAIL_2_ADDRESS, MAIL_2_USERNAME, MAIL_2_PASSWORD],
]


def connect_and_read_email():
    for credential in MAIL_CREDENTIALS:
        print(f"подключение ящик {credential[0]}")
        credentials = Credentials(username=credential[1], password=credential[2])
        try:
            config = Configuration(server=MAIL_SERVER_NAME, credentials=credentials)
            account = Account(
                primary_smtp_address=credential[0],
                credentials=credentials,
                autodiscover=False,
                config=config,
                access_type=DELEGATE,
            )
            print(f"Сервер {account.protocol.service_endpoint}")

            # достаем атачменты писем предыдущего дня
            # таймзона МСК
            moscow_tz = pytz.timezone("Europe/Moscow")

            # временной диапазон предыдущего дня
            today_moscow = datetime.now(moscow_tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            yesterday_start_moscow = today_moscow - timedelta(days=1)
            yesterday_end_moscow = today_moscow - timedelta(microseconds=1)
            # конверсия в EWSDateTime для exchange
            yesterday_start_ews = EWSDateTime.from_datetime(yesterday_start_moscow)
            today_ews = EWSDateTime.from_datetime(today_moscow)
            print("\n" + "=" * 70)
            print("Ищем вложения за предыдущий день")
            print(f" С: {yesterday_start_moscow.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f" По: {yesterday_end_moscow.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print("\n" + "=" * 70)
            messages = account.inbox.filter(
                datetime_received__gte=yesterday_start_ews,
                datetime_received__lt=today_ews,
                has_attachments=True,
            )

            # создаем директорию для скачивания attachments
            attachments_dir = os.path.join(REPORS_DEPO_DIRECTORY or "", DECODE or "")
            if not os.path.exists(attachments_dir):
                os.makedirs(attachments_dir)
                print(f"Создана папка: {attachments_dir}")

            message_count = 0
            total_attachments = 0
            downloaded_files = []
            for message in messages:
                message_count += 1
                print(f"Письмо №{message_count}:")
                print(f"Тема {message.subject}")
                # print(f'От: {message.sender.email_address if message.sender else "N/A"}')
                print(
                    f"Дата: {message.datetime_received.astimezone(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if message.attachments:
                    print("Вложения:")
                    for attachment in message.attachments:
                        total_attachments += 1
                        print(f"Вложения: {attachment.name} ({attachment.size} байт)")
                        # скачиваем вложения
                        if isinstance(attachment, FileAttachment):
                            filename = attachment.name
                            filepath = os.path.join(attachments_dir, filename)

                            # если файл существует, добавляем timestamp
                            if os.path.exists(filepath):
                                # name, ext = os.path.splittext(filename)
                                # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                # filename = f"{filename}_{timestamp}{ext}"
                                filepath = os.path.join(attachments_dir, filename)
                            # сохраняем файл
                            with open(filepath, "wb") as f:
                                f.write(attachment.content)

                            print(f"Сохранен: {filepath}")
                            downloaded_files.append(
                                {
                                    "filename": filename,
                                    "filepath": filepath,
                                    "size": attachment.size,
                                    "from": message.sender.email_address
                                    if message.sender
                                    else "N/A",
                                    "subject": message.subject,
                                }
                            )
            print("\n" + "=" * 70)
            print("Итого найдено")
            print(f"Писем с вложениями: {message_count}")
            print(f"Всего вложений: {total_attachments}")
            print(f"Скачано файлов: {len(downloaded_files)}")
            print(f"Папка с вложениями: {os.path.abspath(attachments_dir)}")
            print("\n" + "=" * 70)
            print("done")
            return True
        except Exception as e:
            print(f"error {e}")
            print("\n")
            traceback.print_exc()
            return False
    return False


if __name__ == "__main__":
    connect_and_read_email()

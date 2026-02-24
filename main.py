import os
import traceback
import pytz
from datetime import datetime, timedelta

from exchangelib import (
    Credentials, Account,
    Configuration, DELEGATE,
    HTMLBody, Message, FileAttachment
)
from exchangelib import EWSDateTime, EWSTimeZone
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter

# from config_ews import (
#     MAIL_USERNAME,
#     MAIL_PASSWORD,
#     MAIL_SERVER_NAME,
#     MAIL_ADDRESS,
#     USE_AUTODISCOVER
# )

from dotenv import load_dotenv

load_dotenv()

MAIL_USERNAME = os.getenv('MAIL_USERNAME')
MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
MAIL_SERVER_NAME = os.getenv('MAIL_SERVER_NAME')
MAIL_ADDRESS = os.getenv('MAIL_ADDRESS')
USE_AUTODISCOVER = os.getenv('USE_AUTODISCOVER', 'False').lower() == 'true'


def connect_and_read_email():
    print('подключение')
    credentials = Credentials(
        username=MAIL_USERNAME,
        password=MAIL_PASSWORD
    )
    try:
        # if USE_AUTODISCOVER:
        #     print(f'Autodiscover for {MAIL_ADDRESS}')
        #     account = Account(
        #         primary_smtp_address=MAIL_ADDRESS,
        #         credentials=credentials,
        #         autodiscover=True,
        #         access_type=DELEGATE
        #     )
        # else:
        config = Configuration(
            server=MAIL_SERVER_NAME,
            credentials=credentials
        )
        account = Account(
            primary_smtp_address=MAIL_ADDRESS,
            credentials=credentials,
            autodiscover=False,
            config=config,
            access_type=DELEGATE
        )
        print(f'Сервер {account.protocol.service_endpoint}')
        
        # Получаем таймзону Москва (UTC+3)
        moscow_tz = pytz.timezone('Europe/Moscow')
        
        # Определяем временной диапазон за сегодня (с 00:00 по Москве до текущего момента)
        now_moscow = datetime.now(moscow_tz)
        today_start_moscow = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Конвертируем в EWSDateTime для Exchange
        today_start_ews = EWSDateTime.from_datetime(today_start_moscow)
        now_ews = EWSDateTime.from_datetime(now_moscow)
        
        print(f'\nПоиск писем с вложениями за сегодня:')
        print(f'  С: {today_start_moscow.strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'  По: {now_moscow.strftime("%Y-%m-%d %H:%M:%S")}')
        
        # Фильтруем письма за сегодня с вложениями
        messages = account.inbox.filter(
            datetime_received__gte=today_start_ews,
            datetime_received__lte=now_ews,
            has_attachments=True
        )
        
        # Создаём папку для вложений
        attachments_dir = os.path.join('test', 'attachments')
        if not os.path.exists(attachments_dir):
            os.makedirs(attachments_dir)
            print(f'Создана папка: {attachments_dir}')
        
        # Собираем информацию о письмах и вложениях
        message_count = 0
        total_attachments = 0
        downloaded_files = []
        
        for message in messages:
            message_count += 1
            print(f'\n📧 Письмо #{message_count}:')
            print(f'   Тема: {message.subject}')
            print(f'   От: {message.sender.email_address if message.sender else "N/A"}')
            print(f'   Дата: {message.datetime_received.astimezone(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")}')
            
            if message.attachments:
                print(f'   Вложения:')
                for attachment in message.attachments:
                    total_attachments += 1
                    print(f'     📎 {attachment.name} ({attachment.size} байт)')
                    
                    # Скачиваем вложение
                    if isinstance(attachment, FileAttachment):
                        filename = attachment.name
                        filepath = os.path.join(attachments_dir, filename)
                        
                        # Если файл существует, добавляем timestamp
                        if os.path.exists(filepath):
                            name, ext = os.path.splitext(filename)
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            filename = f"{name}_{timestamp}{ext}"
                            filepath = os.path.join(attachments_dir, filename)
                        
                        # Сохраняем файл
                        with open(filepath, 'wb') as f:
                            f.write(attachment.content)
                        
                        print(f'        ✓ Сохранён: {filepath}')
                        downloaded_files.append({
                            'filename': filename,
                            'filepath': filepath,
                            'size': attachment.size,
                            'from': message.sender.email_address if message.sender else 'N/A',
                            'subject': message.subject
                        })
        
        print(f'\n{"="*70}')
        print(f'Итого найдено:')
        print(f'  Писем с вложениями: {message_count}')
        print(f'  Всего вложений: {total_attachments}')
        print(f'  Скачано файлов: {len(downloaded_files)}')
        print(f'  Папка с вложениями: {os.path.abspath(attachments_dir)}')
        print(f'{"="*70}')
        print('done')
    except Exception as e:
        print(f'error {e}')
        print('\n')
        traceback.print_exc()
        return False
    return True


if __name__ == '__main__':
    connect_and_read_email()

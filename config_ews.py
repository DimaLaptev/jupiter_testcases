import os
from dotenv import load_dotenv

load_dotenv()

MAIL_SERVER_NAME = os.getenv("MAIL_SERVER_NAME")

MAIL_1_ADDRESS = os.getenv("MAIL_1_ADDRESS")
MAIL_1_USERNAME = os.getenv("MAIL_1_USERNAME")
MAIL_1_PASSWORD = os.getenv("MAIL_1_PASSWORD")

MAIL_2_ADDRESS = os.getenv("MAIL_2_ADDRESS")
MAIL_2_USERNAME = os.getenv("MAIL_2_USERNAME")
MAIL_2_PASSWORD = os.getenv("MAIL_2_PASSWORD")

# Получатели отчётов валидации (validation report recipients)
GPB_VALIDATION_RECIPIENT = os.getenv("GPB_VALIDATION_RECIPIENT")
RSD_VALIDATION_RECIPIENT = os.getenv("RSD_VALIDATION_RECIPIENT")

USE_AUTODISCOVER = os.getenv("USE_AUTODISCOVER", "False").lower()

# Директории (directories) для обработки файлов
REPORS_DEPO_DIRECTORY = os.getenv("REPORS_DEPO_DIRECTORY")
GPB_BASE_DIR = os.getenv("REPORS_DEPO_DIRECTORY")
DECODE = os.getenv("DECODE")
DOMRF_OPEN_DIR = os.getenv("DOMRF_OPEN_DIR")
DOMRFIA_OPEN_DIR = os.getenv("DOMRFIA_OPEN_DIR")
DOMRF_SECRET_DIR = os.getenv("DOMRF_SECRET_DIR")
DOMRFIA_SECRET_DIR = os.getenv("DOMRFIA_SECRET_DIR")
EIS_DIR = os.getenv("EIS_DIR")
REPORTS_DIR = os.getenv("REPORTS_DIR")

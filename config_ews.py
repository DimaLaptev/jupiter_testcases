import os
from dotenv import load_dotenv

load_dotenv()

# Новые названия переменных
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_SERVER_NAME = os.getenv("MAIL_SERVER_NAME", "")
MAIL_ADDRESS = os.getenv("MAIL_ADDRESS", "")
USE_AUTODISCOVER = os.getenv("USE_AUTODISCOVER", "False").lower() == "true"
VERIFY_SSL = os.getenv("VERIFY_SSL", "True").lower() == "true"

# Старые названия для обратной совместимости
EXCHANGE_EMAIL = MAIL_ADDRESS
EXCHANGE_PASSWORD = MAIL_PASSWORD
EXCHANGE_SERVER = MAIL_SERVER_NAME

# Директории (directories) для обработки файлов
DOMRF_OPEN_DIR = os.getenv("DOMRF_OPEN_DIR", "./DOMRF/open")
DOMRFIA_OPEN_DIR = os.getenv("DOMRFIA_OPEN_DIR", "./DOMRFIA/open")
GPB_BASE_DIR = os.getenv("GPB_BASE_DIR", "./")


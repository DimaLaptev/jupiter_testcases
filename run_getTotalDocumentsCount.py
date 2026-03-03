"""
Отправка одного SOAP-запроса getTotalDocumentsCount.
Подставьте свои данные прямо в request_getTotalDocumentsCount.xml
и запустите: python run_getTotalDocumentsCount.py
"""

import sys
from pathlib import Path

# URL сервиса (без ?wsdl)
ENDPOINT = "https://edo.region.ru/soap/soapdotnet/soap"

# Путь к XML-файлу с телом запроса (редактируйте его)
REQUEST_XML_PATH = Path(__file__).resolve().parent / "request_getTotalDocumentsCount.xml"


def main():
    xml_path = REQUEST_XML_PATH
    if not xml_path.exists():
        print(f"Файл не найден: {xml_path}")
        sys.exit(1)

    body = xml_path.read_text(encoding="utf-8")

    import requests
    response = requests.post(
        ENDPOINT,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"getTotalDocumentsCount"',
        },
        timeout=60,
    )

    print("Status:", response.status_code)
    print("Response:")
    print(response.text)


if __name__ == "__main__":
    main()

"""Разбивает PDF на отдельные файлы: по одной странице в каждом."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

# Путь к исходному PDF (рядом со скриптом или абсолютный путь)
INPUT_PDF = "input.pdf"

# Папка для результата; None — создать {stem}_pages рядом с исходником
OUTPUT_DIR = None


def split_pdf(input_pdf: Path, output_dir: Path | None = None) -> Path:
    if not input_pdf.is_file():
        raise FileNotFoundError(f"Файл не найден: {input_pdf.resolve()}")

    if output_dir is None:
        output_dir = input_pdf.parent / f"{input_pdf.stem}_pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(input_pdf))
    page_count = len(reader.pages)

    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        out_path = output_dir / f"page_{i:03d}.pdf"
        with out_path.open("wb") as f:
            writer.write(f)

    print(f"Страниц: {page_count}")
    print(f"Результат: {output_dir.resolve()}")
    return output_dir


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    input_path = Path(INPUT_PDF)
    if not input_path.is_absolute():
        input_path = script_dir / input_path

    out = Path(OUTPUT_DIR) if OUTPUT_DIR else None
    if out is not None and not out.is_absolute():
        out = script_dir / out

    split_pdf(input_path, out)


if __name__ == "__main__":
    main()

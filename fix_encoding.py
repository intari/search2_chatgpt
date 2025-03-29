# File: fix_encoding.py
import os
import codecs # Используем codecs для явного указания кодировок при чтении/записи
import argparse
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def ensure_utf8_encoding(filename: str, source_encoding: str = 'cp1251') -> bool:
    """
    Проверяет кодировку файла. Если не UTF-8, пытается конвертировать из source_encoding.
    Возвращает True, если была произведена конвертация, False иначе.
    """
    is_converted = False
    try:
        # 1. Пробуем прочитать как UTF-8, чтобы не трогать уже корректные файлы
        with codecs.open(filename, "r", encoding='utf-8') as f:
            f.read() # Просто читаем, чтобы проверить декодирование
        logging.debug(f"Файл {filename} уже в UTF-8.")
        return False # Конвертация не требуется
    except UnicodeDecodeError:
        # Файл точно не UTF-8, пробуем конвертировать из предполагаемой source_encoding
        logging.info(f"Файл {filename} не в UTF-8. Попытка конвертации из {source_encoding}...")
        try:
            # Читаем с исходной кодировкой
            with codecs.open(filename, "r", encoding=source_encoding) as f:
                content = f.read()

            # Перезаписываем файл в UTF-8
            # Важно: Используем 'w' режим, который перезапишет файл
            with codecs.open(filename, "w", encoding='utf-8') as f:
                f.write(content)

            logging.info(f"✅ {filename} успешно конвертирован из {source_encoding} в UTF-8!")
            is_converted = True
        except UnicodeDecodeError:
            # Не удалось прочитать даже как source_encoding
            logging.warning(f"⚠️ Не удалось прочитать {filename} как {source_encoding} (после неудачи с UTF-8). Файл не изменен.")
        except Exception as e:
            logging.error(f"❌ Ошибка конвертации файла {filename} из {source_encoding}: {e}. Файл не изменен.")
    except FileNotFoundError:
        logging.error(f"Файл не найден при попытке конвертации: {filename}")
    except Exception as e:
        # Ловим другие возможные ошибки чтения на этапе проверки UTF-8
        logging.error(f"Не удалось прочитать файл {filename} для проверки/конвертации: {e}")

    return is_converted


def fix_all_files(directory: str, source_encoding: str = 'cp1251') -> None:
    """
    Обходит директорию и конвертирует текстовые файлы из source_encoding в UTF-8,
    если они еще не в UTF-8.
    """
    converted_count = 0
    processed_count = 0
    # Список расширений текстовых файлов для обработки
    text_extensions = ('.txt', '.md', '.html', '.htm', '.css', '.js', '.json', '.xml', '.csv', '.log', '.srt') # Добавь нужные

    for root, _, files in os.walk(directory):
        for file in files:
            # Проверяем расширение файла
            if file.lower().endswith(text_extensions):
                 filepath = os.path.join(root, file)
                 processed_count += 1
                 if ensure_utf8_encoding(filepath, source_encoding):
                      converted_count += 1
            else:
                 logging.debug(f"Пропуск файла с нетекстовым расширением: {file}")

    logging.info(f"Проверено текстовых файлов: {processed_count}. Конвертировано в UTF-8: {converted_count}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Конвертация текстовых файлов из указанной кодировки (по умолч. cp1251) в UTF-8.")
    parser.add_argument("directory", type=str, help="Путь к директории для конвертации.")
    parser.add_argument(
        "--source-encoding",
        type=str,
        default="cp1251",
        help="Предполагаемая исходная кодировка файлов, не являющихся UTF-8 (по умолчанию: cp1251).",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        logging.error(f"Указанный путь не является директорией: {args.directory}")
    else:
        logging.info(f"🛠️ Запуск исправления кодировки в директории: {args.directory}...")
        logging.info(f"Предполагаемая исходная кодировка для конвертации: {args.source_encoding}")
        fix_all_files(args.directory, args.source_encoding)
        logging.info("✅ Исправление кодировки завершено!")

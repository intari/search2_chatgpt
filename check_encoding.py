# File: check_encoding.py
import os
import argparse
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def is_likely_utf8(filename: str) -> bool:
    """
    Проверяет, можно ли успешно декодировать файл как UTF-8.
    Возвращает True, если файл успешно декодирован или если возникла ошибка чтения файла.
    Возвращает False, если произошла ошибка UnicodeDecodeError.
    """
    try:
        with open(filename, "rb") as f:
            # Читаем весь файл. Для очень больших файлов можно ограничить чтение.
            f.read().decode('utf-8')
        return True
    except UnicodeDecodeError:
        # Это точно не UTF-8
        return False
    except FileNotFoundError:
        logging.error(f"Файл не найден при проверке UTF-8: {filename}")
        # Не можем быть уверены, но для целей проверки считаем 'проблемным'
        return False
    except Exception as e:
        logging.error(f"Не удалось прочитать файл {filename} для проверки UTF-8: {e}")
        # Не можем быть уверены, но для целей проверки считаем 'проблемным'
        return False

def check_all_files_not_utf8(directory: str) -> None:
    """Проверяет все файлы в директории, сообщая о тех, что не в UTF-8."""
    found_non_utf8 = False
    checked_files = 0
    problematic_files = []

    for root, _, files in os.walk(directory):
        for file in files:
            # Ограничимся проверкой текстовых файлов по расширению
            if file.lower().endswith(('.txt', '.md', '.html', '.css', '.js', '.json', '.xml', '.csv')):
                 filepath = os.path.join(root, file)
                 checked_files += 1
                 if not is_likely_utf8(filepath):
                      problematic_files.append(filepath)
                      found_non_utf8 = True

    logging.info(f"Проверено файлов с текстовыми расширениями: {checked_files}")
    if found_non_utf8:
        logging.warning(f"Найдены файлы ({len(problematic_files)}), которые не удалось прочитать как UTF-8:")
        # Попробуем угадать кодировку для проблемных файлов, если chardet доступен
        try:
            import chardet
            logging.info("Попытка определить кодировку для проблемных файлов (требуется chardet)...")
            for filepath in problematic_files:
                try:
                    with open(filepath, "rb") as f:
                        raw_data = f.read(8192) # Читаем начало файла для chardet
                        if not raw_data: continue # Пропускаем пустые
                        result = chardet.detect(raw_data)
                        encoding = result["encoding"] or "N/A"
                        confidence = result["confidence"] or 0.0
                        logging.warning(f"  - {filepath} (предположительно {encoding}, уверенность {confidence:.2f})")
                except Exception as e:
                    logging.warning(f"  - {filepath} (не удалось определить кодировку: {e})")

        except ImportError:
            logging.warning("Модуль 'chardet' не установлен. Установите его (`pip install chardet`), чтобы попытаться определить кодировку автоматически.")
            for filepath in problematic_files:
                 logging.warning(f"  - {filepath}")
    else:
        logging.info("Все проверенные файлы успешно читаются как UTF-8.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Проверка текстовых файлов на соответствие кодировке UTF-8.")
    parser.add_argument("directory", type=str, help="Путь к директории для проверки.")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        logging.error(f"Указанный путь не является директорией: {args.directory}")
    else:
        logging.info(f"🔍 Поиск файлов не в UTF-8 в директории: {args.directory}...")
        check_all_files_not_utf8(args.directory)
        logging.info("✅ Проверка завершена!")

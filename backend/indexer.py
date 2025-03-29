import os
import requests
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Set
from pdfminer.high_level import extract_text as pdf_extract_text
from pdfminer.pdfparser import PDFSyntaxError
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
FILES_DIR: str = os.getenv("LOCAL_STORAGE_PATH", "/mnt/storage")
SEARCH_ENGINE_URL: str = os.getenv("MEILI_URL", "http://meilisearch:7700")
MEILI_API_KEY: Optional[str] = os.getenv("MEILI_MASTER_KEY") # Используйте Master Key или Index API Key
INDEX_NAME: str = "documents"
BATCH_SIZE: int = 100 # Количество документов для отправки в Meilisearch за раз

# --- Функции извлечения текста ---

def extract_text_from_txt(file_path: Path) -> str:
    """Извлекает текст из TXT файла, пробуя разные кодировки."""
    encodings_to_try = ['utf-8', 'cp1251', 'latin-1']
    for encoding in encodings_to_try:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise IOError(f"Не удалось прочитать TXT файл {file_path} даже после попыток смены кодировки.") from e
    # Если ни одна кодировка не подошла
    logger.warning(f"Не удалось определить кодировку для TXT файла: {file_path.name}. Пропускаем.")
    raise ValueError(f"Unknown encoding for {file_path.name}")


def extract_text_from_pdf(file_path: Path) -> str:
    """Извлекает текст из PDF файла."""
    try:
        return pdf_extract_text(str(file_path))
    except PDFSyntaxError as e:
        raise ValueError(f"Ошибка синтаксиса PDF: {file_path.name}") from e
    except Exception as e:
        # Ловим другие возможные ошибки pdfminer
        raise IOError(f"Не удалось обработать PDF файл {file_path.name}") from e

def extract_text_from_epub(file_path: Path) -> str:
    """Извлекает текст из EPUB файла."""
    try:
        book = epub.read_epub(str(file_path))
        text_parts: List[str] = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.content, "html.parser")
            # Удаляем скрипты и стили, чтобы не индексировать их содержимое
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            # Получаем текст, разделяя блоки параграфами для лучшей читаемости
            # Используем strip=True для удаления лишних пробелов по краям
            block_text = soup.get_text(separator='\n', strip=True)
            if block_text:
                text_parts.append(block_text)
        return "\n\n".join(text_parts) # Разделяем контент разных HTML-файлов двойным переносом строки
    except KeyError as e:
        # Иногда возникает при проблемах с оглавлением или структурой epub
         raise ValueError(f"Ошибка структуры EPUB файла: {file_path.name}, KeyError: {e}") from e
    except Exception as e:
        raise IOError(f"Не удалось обработать EPUB файл {file_path.name}") from e

# --- Функции взаимодействия с Meilisearch ---

def get_meili_client() -> requests.Session:
    """Создает и настраивает HTTP клиент для Meilisearch."""
    session = requests.Session()
    headers = {}
    if MEILI_API_KEY:
        headers['Authorization'] = f'Bearer {MEILI_API_KEY}'
    session.headers.update(headers)
    return session

def get_indexed_files(client: requests.Session) -> Dict[str, float]:
    """Получает список ID и время модификации проиндексированных файлов из Meilisearch."""
    indexed_files: Dict[str, float] = {}
    offset = 0
    limit = 1000 # Получаем по 1000 за раз
    url = f"{SEARCH_ENGINE_URL}/indexes/{INDEX_NAME}/documents"
    params = {"limit": limit, "fields": "id,file_mtime"}

    while True:
        try:
            params["offset"] = offset
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if not results:
                break # Больше нет документов

            for doc in results:
                 # Убедимся, что file_mtime существует и является числом
                 mtime = doc.get("file_mtime")
                 if isinstance(mtime, (int, float)):
                      indexed_files[doc['id']] = float(mtime)
                 else:
                     # Если времени модификации нет, считаем, что файл нужно переиндексировать
                      indexed_files[doc['id']] = 0.0

            offset += len(results)

            # Защита от бесконечного цикла, если API вернет некорректные данные
            if len(results) < limit:
                break

        except requests.exceptions.HTTPError as e:
             # Если индекс не найден (404), это нормально при первом запуске
            if e.response.status_code == 404:
                logger.info(f"Индекс '{INDEX_NAME}' не найден. Будет создан при первой индексации.")
                return {} # Возвращаем пустой словарь
            else:
                 logger.error(f"Ошибка получения документов из Meilisearch: {e}")
                 raise # Передаем ошибку дальше, т.к. не можем продолжить
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка соединения с Meilisearch ({url}): {e}")
            raise
    logger.info(f"Найдено {len(indexed_files)} документов в индексе '{INDEX_NAME}'.")
    return indexed_files

def update_meili_index(client: requests.Session, documents: List[Dict[str, Any]]) -> None:
    """Отправляет пакет документов в Meilisearch для добавления/обновления."""
    if not documents:
        return
    url = f"{SEARCH_ENGINE_URL}/indexes/{INDEX_NAME}/documents"
    try:
        # Отправляем частями (батчами)
        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i:i + BATCH_SIZE]
            response = client.post(url, json=batch)
            response.raise_for_status()
            task_info = response.json()
            logger.info(f"Отправлено {len(batch)} документов на индексацию. Task UID: {task_info.get('taskUid', 'N/A')}")
            # В продакшене можно добавить мониторинг статуса задачи Meilisearch
            time.sleep(0.1) # Небольшая пауза между батчами

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке документов в Meilisearch: {e}")
        # Можно добавить логику повторной попытки или сохранения неудавшихся батчей

def delete_from_meili_index(client: requests.Session, file_ids: List[str]) -> None:
    """Удаляет документы из Meilisearch по списку ID."""
    if not file_ids:
        return
    url = f"{SEARCH_ENGINE_URL}/indexes/{INDEX_NAME}/documents/delete-batch"
    try:
        # Удаляем частями (батчами)
        for i in range(0, len(file_ids), BATCH_SIZE):
             batch_ids = file_ids[i:i + BATCH_SIZE]
             response = client.post(url, json=batch_ids)
             response.raise_for_status()
             task_info = response.json()
             logger.info(f"Отправлено {len(batch_ids)} ID на удаление. Task UID: {task_info.get('taskUid', 'N/A')}")
             time.sleep(0.1) # Небольшая пауза

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при удалении документов из Meilisearch: {e}")

# --- Основная логика индексации ---

def process_file(file_path: Path) -> Optional[Dict[str, Any]]:
    """Обрабатывает один файл: извлекает текст и формирует документ для Meilisearch."""
    filename = file_path.name
    file_mtime = os.path.getmtime(str(file_path))
    content = None
    file_ext = file_path.suffix.lower()

    try:
        logger.debug(f"Обработка файла: {filename}")
        if file_ext == ".txt":
            content = extract_text_from_txt(file_path)
        elif file_ext == ".pdf":
            content = extract_text_from_pdf(file_path)
        elif file_ext == ".epub":
            content = extract_text_from_epub(file_path)
        else:
            logger.debug(f"Неподдерживаемый формат файла: {filename}. Пропускаем.")
            return None # Неподдерживаемый формат

        if content is None or not content.strip():
            logger.warning(f"Не удалось извлечь текст или текст пуст: {filename}")
            return None

        # Формируем документ для Meilisearch
        document = {
            "id": filename, # Используем имя файла как уникальный ID
            "content": content.strip(),
            "file_mtime": file_mtime, # Сохраняем время модификации
            "indexed_at": time.time() # Время последней индексации
        }
        return document

    except (ValueError, IOError, Exception) as e:
        # Ловим ошибки чтения, парсинга или другие проблемы с файлом
        logger.error(f"❌ Ошибка обработки файла {filename}: {e}")
        return None # Пропускаем этот файл

def scan_and_index_files() -> None:
    """Сканирует директорию, сравнивает с индексом и обновляет Meilisearch."""
    logger.info(f"🚀 Запуск сканирования директории: {FILES_DIR}")
    target_dir = Path(FILES_DIR)
    if not target_dir.is_dir():
        logger.error(f"Директория не найдена: {FILES_DIR}")
        return

    client = get_meili_client()

    # 1. Получаем состояние индекса
    try:
        indexed_files_mtimes: Dict[str, float] = get_indexed_files(client)
    except Exception as e:
        logger.error(f"Не удалось получить состояние индекса. Прерывание: {e}")
        return

    # 2. Сканируем локальные файлы
    local_files_mtimes: Dict[str, float] = {}
    files_to_process: List[Path] = []
    processed_extensions = {".txt", ".pdf", ".epub"}

    for item in target_dir.rglob('*'): # Рекурсивно обходим все файлы
        if item.is_file() and item.suffix.lower() in processed_extensions:
             try:
                  local_files_mtimes[item.name] = item.stat().st_mtime
                  files_to_process.append(item)
             except FileNotFoundError:
                 logger.warning(f"Файл был удален во время сканирования: {item.name}")
                 continue # Пропускаем, если файл исчез между листингом и stat()

    logger.info(f"Найдено {len(local_files_mtimes)} поддерживаемых файлов локально.")

    # 3. Определяем изменения
    local_filenames: Set[str] = set(local_files_mtimes.keys())
    indexed_filenames: Set[str] = set(indexed_files_mtimes.keys())

    files_to_add: Set[str] = local_filenames - indexed_filenames
    files_to_delete: Set[str] = indexed_filenames - local_filenames
    files_to_check_for_update: Set[str] = local_filenames.intersection(indexed_filenames)

    files_to_update: Set[str] = {
        fname for fname in files_to_check_for_update
        if local_files_mtimes[fname] > indexed_files_mtimes.get(fname, 0.0) # Сравниваем время модификации
    }

    logger.info(f"К добавлению: {len(files_to_add)}, к обновлению: {len(files_to_update)}, к удалению: {len(files_to_delete)}")

    # 4. Обрабатываем и отправляем добавления/обновления
    docs_for_meili: List[Dict[str, Any]] = []
    files_requiring_processing: Set[str] = files_to_add.union(files_to_update)

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for file_path in files_to_process:
        if file_path.name in files_requiring_processing:
            processed_count +=1
            document = process_file(file_path)
            if document:
                docs_for_meili.append(document)
            else:
                error_count += 1 # Ошибка или не удалось извлечь текст
        else:
             skipped_count +=1 # Файл не изменился

    logger.info(f"Обработано файлов: {processed_count} (пропущено без изменений: {skipped_count}, ошибки: {error_count})")

    if docs_for_meili:
        logger.info(f"Отправка {len(docs_for_meili)} документов в Meilisearch...")
        update_meili_index(client, docs_for_meili)
    else:
        logger.info("Нет новых или обновленных файлов для индексации.")

    # 5. Удаляем устаревшие документы
    if files_to_delete:
        logger.info(f"Удаление {len(files_to_delete)} устаревших документов из Meilisearch...")
        delete_from_meili_index(client, list(files_to_delete))
    else:
        logger.info("Нет файлов для удаления из индекса.")

    logger.info("✅ Индексация завершена.")


if __name__ == "__main__":
    scan_and_index_files()

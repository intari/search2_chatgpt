import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import os
import time # Добавим для мокирования time.time

# Мокирование load_dotenv (выполняется до импорта indexer)
patcher_dotenv_indexer = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_indexer.start()

# Импортируем модуль indexer ПОСЛЕ старта патчера dotenv
from backend import indexer

# Фикстура для остановки патчера dotenv после всех тестов модуля
@pytest.fixture(scope="module", autouse=True)
def stop_indexer_patch():
    yield
    try:
        patcher_dotenv_indexer.stop()
    except RuntimeError: # Если уже остановлен
        pass


# --- Тесты для функций извлечения текста ---

def test_extract_text_from_txt_success():
    """Тестирует успешное чтение UTF-8 TXT файла."""
    mock_content = "Привет, мир!"
    # Мокируем напрямую read_text у класса Path
    with patch.object(Path, 'read_text', return_value=mock_content) as mock_read:
        # Создаем фиктивный объект Path для вызова функции
        dummy_path = Path("dummy.txt")
        result = indexer.extract_text_from_txt(dummy_path)
        assert result == mock_content
        # Проверяем, что read_text был вызван с кодировкой utf-8
        mock_read.assert_called_once_with(encoding='utf-8')

def test_extract_text_from_txt_cp1251():
    """Тестирует чтение TXT файла в CP1251 после неудачи с UTF-8."""
    mock_content_cp1251_str = "Тест CP1251"
    # Настраиваем side_effect для имитации попыток чтения
    mock_read_text = MagicMock(name='read_text_mock')
    mock_read_text.side_effect = [
        # Ошибка при первой попытке (UTF-8)
        UnicodeDecodeError('utf-8', b'\xd2\xe5\xf1\xf2', 0, 1, 'invalid start byte'),
        # Успешный результат при второй попытке (CP1251)
        mock_content_cp1251_str,
        # Результат для третьей попытки (Latin-1), на всякий случай
        mock_content_cp1251_str
    ]
    with patch.object(Path, 'read_text', mock_read_text):
        dummy_path = Path("dummy_cp1251.txt")
        result = indexer.extract_text_from_txt(dummy_path)
        assert result == mock_content_cp1251_str
        # Проверяем, что было две попытки вызова read_text
        assert mock_read_text.call_count == 2
        # Проверяем аргументы кодировки для каждой попытки
        assert mock_read_text.call_args_list[0][1]['encoding'] == 'utf-8'
        assert mock_read_text.call_args_list[1][1]['encoding'] == 'cp1251'


def test_extract_text_from_txt_unknown_encoding():
    """Тестирует случай, когда ни одна кодировка не подходит."""
    # Имитируем ошибку UnicodeDecodeError для всех трех попыток
    mock_read_text = MagicMock(name='read_text_mock_fail')
    mock_read_text.side_effect = [
        UnicodeDecodeError('utf-8', b'\xff\xfe', 0, 1, 'invalid bom'),
        UnicodeDecodeError('cp1251', b'\xff\xfe', 0, 1, 'invalid sequence'),
        UnicodeDecodeError('latin-1', b'\xff\xfe', 0, 1, 'invalid sequence')
    ]
    with patch.object(Path, 'read_text', mock_read_text), \
         pytest.raises(ValueError, match="Unknown encoding for dummy_unknown.txt"): # Ожидаем ValueError
         dummy_path = Path("dummy_unknown.txt")
         indexer.extract_text_from_txt(dummy_path)
    # Проверяем, что было сделано 3 попытки вызова read_text
    assert mock_read_text.call_count == 3


@patch('backend.indexer.pdf_extract_text', return_value="PDF content here")
def test_extract_text_from_pdf_success(mock_pdf_extract):
    """Тестирует успешное извлечение текста из PDF."""
    dummy_path = Path("dummy.pdf")
    result = indexer.extract_text_from_pdf(dummy_path)
    assert result == "PDF content here"
    # Убедимся, что pdf_extract_text вызывается со строковым представлением пути
    mock_pdf_extract.assert_called_once_with(str(dummy_path))


@patch('backend.indexer.pdf_extract_text', side_effect=indexer.PDFSyntaxError("Bad PDF"))
def test_extract_text_from_pdf_syntax_error(mock_pdf_extract):
    """Тестирует обработку PDFSyntaxError."""
    dummy_path = Path("dummy.pdf")
    with pytest.raises(ValueError, match="Ошибка синтаксиса PDF: dummy.pdf"):
        indexer.extract_text_from_pdf(dummy_path)


@patch('backend.indexer.epub.read_epub')
def test_extract_text_from_epub_success(mock_read_epub):
    """Тестирует успешное извлечение текста из EPUB."""
    # Создаем моки для epub объектов
    mock_item1 = MagicMock(); mock_item1.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item1.content = b"<html><body><p>First paragraph.</p></body></html>"
    mock_item2 = MagicMock(); mock_item2.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item2.content = b"<html><body><style>.test{}</style><p>Second.</p><script>alert();</script><div>Third</div></body></html>"
    mock_book = MagicMock(); mock_book.get_items_of_type.return_value = [mock_item1, mock_item2]
    mock_read_epub.return_value = mock_book # Настраиваем мок read_epub

    dummy_path = Path("dummy.epub")
    result = indexer.extract_text_from_epub(dummy_path)
    # Проверяем результат с учетом удаления тегов и добавления переносов строк
    assert result == "First paragraph.\n\nSecond.\nThird"
    # Убедимся, что read_epub вызывается со строковым представлением пути
    mock_read_epub.assert_called_once_with(str(dummy_path))
    mock_book.get_items_of_type.assert_called_once_with(indexer.ITEM_DOCUMENT)


@patch('backend.indexer.epub.read_epub', side_effect=Exception("EPUB Read Error"))
def test_extract_text_from_epub_error(mock_read_epub):
    """Тестирует обработку общей ошибки при чтении EPUB."""
    dummy_path = Path("dummy.epub")
    with pytest.raises(IOError, match="Не удалось обработать EPUB файл dummy.epub"):
        indexer.extract_text_from_epub(dummy_path)


# --- Тесты для process_file ---

# Мокируем зависимости для process_file
@patch('pathlib.Path.stat') # Используется для получения mtime
@patch('backend.indexer.extract_text_from_txt') # Мокируем функцию извлечения
@patch('backend.indexer.time.time', return_value=99999.99) # Мокируем текущее время
def test_process_file_txt_success(mock_time, mock_extract, mock_stat):
    """Тестирует успешную обработку TXT файла."""
    # Настройка моков
    mock_stat_result = MagicMock(); mock_stat_result.st_mtime = 12345.67
    mock_stat.return_value = mock_stat_result
    mock_extract.return_value="Текстовый контент" # Что вернет функция извлечения

    # Создаем мок объекта Path для передачи в process_file
    p = MagicMock(spec=Path)
    p.name = "file.txt"
    p.suffix = ".txt"
    # Важно: нужно чтобы str(p) возвращало имя файла для логов и т.п.
    p.__str__.return_value = "file.txt"

    result = indexer.process_file(p)

    assert result is not None
    assert result["id"] == "file.txt"
    assert result["content"] == "Текстовый контент"
    assert result["file_mtime"] == 12345.67
    assert result["indexed_at"] == 99999.99 # Проверяем мок времени
    # Проверяем, что были вызваны нужные функции/методы
    mock_extract.assert_called_once_with(p)
    p.stat.assert_called_once() # Проверяем вызов stat у мока Path


@patch('pathlib.Path.stat') # stat не должен вызваться
@patch('backend.indexer.extract_text_from_pdf', side_effect=IOError("PDF read failed"))
def test_process_file_pdf_error(mock_extract, mock_stat):
    """Тестирует обработку ошибки при извлечении текста из PDF."""
    p = MagicMock(spec=Path)
    p.name = "broken.pdf"
    p.suffix = ".pdf"
    p.__str__.return_value = "broken.pdf"

    result = indexer.process_file(p)

    assert result is None # Ожидаем None при ошибке извлечения
    mock_extract.assert_called_once_with(p) # Проверяем, что попытка извлечения была
    mock_stat.assert_not_called() # stat не должен вызваться, т.к. функция вышла раньше


# Мокируем все функции извлечения, чтобы убедиться, что они НЕ вызываются
@patch('backend.indexer.extract_text_from_txt')
@patch('backend.indexer.extract_text_from_pdf')
@patch('backend.indexer.extract_text_from_epub')
@patch('pathlib.Path.stat') # stat тоже не должен вызваться
def test_process_file_unsupported_extension(mock_stat, mock_epub, mock_pdf, mock_txt):
    """Тестирует обработку файла с неподдерживаемым расширением."""
    p = MagicMock(spec=Path)
    p.name = "image.jpg"
    p.suffix = ".jpg"
    p.__str__.return_value = "image.jpg"

    result = indexer.process_file(p)

    assert result is None
    # Убедимся, что ни одна функция извлечения не вызывалась
    mock_txt.assert_not_called()
    mock_pdf.assert_not_called()
    mock_epub.assert_not_called()
    mock_stat.assert_not_called()


# --- Тесты для основной логики (scan_and_index_files) ---
# Мокируем все внешние зависимости scan_and_index_files
@patch('backend.indexer.Path') # Мокируем сам класс Path
@patch('backend.indexer.get_meili_client')
@patch('backend.indexer.get_indexed_files')
@patch('backend.indexer.update_meili_index')
@patch('backend.indexer.delete_from_meili_index')
@patch('backend.indexer.process_file') # Мокируем обработку отдельного файла
def test_scan_and_index_new_file(
    mock_process_file, mock_delete, mock_update, mock_get_indexed, mock_client_func, MockPath
):
    """Тестирует сценарий добавления нового файла."""
    # 1. Настройка моков
    # Мок клиента Meilisearch
    mock_meili_client_instance = MagicMock()
    mock_client_func.return_value = mock_meili_client_instance
    # Мок ответа от Meilisearch (индекс пуст)
    mock_get_indexed.return_value = {}

    # Мок объекта Path, представляющего директорию
    mock_target_dir_instance = MagicMock(spec=Path)
    mock_target_dir_instance.is_dir.return_value = True
    # Настроим конструктор Path, чтобы он возвращал наш мок директории
    MockPath.return_value = mock_target_dir_instance

    # Мок объекта Path, представляющего новый файл
    new_file_path_mock = MagicMock(spec=Path)
    new_file_path_mock.name = "new.txt"
    new_file_path_mock.is_file.return_value = True
    new_file_path_mock.suffix = ".txt"
    # Мок для stat().st_mtime
    stat_mock = MagicMock(); stat_mock.st_mtime = 100.0
    new_file_path_mock.stat.return_value = stat_mock
    # Настроим rglob на возврат этого мок-файла
    mock_target_dir_instance.rglob.return_value = [new_file_path_mock]

    # Мок результата успешной обработки файла
    mock_process_file.return_value = {"id": "new.txt", "content": "new file", "file_mtime": 100.0, "indexed_at": 101.0}

    # 2. Запуск тестируемой функции
    indexer.scan_and_index_files()

    # 3. Проверки вызовов
    # Проверяем, что был создан Path для нужной директории
    MockPath.assert_called_once_with(indexer.FILES_DIR)
    # Проверяем, что была вызвана проверка is_dir
    mock_target_dir_instance.is_dir.assert_called_once()
    # Проверяем получение клиента Meili
    mock_client_func.assert_called_once()
    # Проверяем получение состояния индекса
    mock_get_indexed.assert_called_once_with(mock_meili_client_instance)
    # Проверяем сканирование файлов
    mock_target_dir_instance.rglob.assert_called_once_with('*')
    # Проверяем вызов stat для найденного файла
    new_file_path_mock.stat.assert_called_once()
     # Проверяем вызов обработки файла
    mock_process_file.assert_called_once_with(new_file_path_mock)
    # Проверяем вызов обновления индекса
    mock_update.assert_called_once()
    # Проверяем аргументы, переданные в update_meili_index
    call_args, _ = mock_update.call_args
    assert call_args[0] is mock_meili_client_instance # Проверяем переданный клиент
    assert len(call_args[1]) == 1 # Проверяем, что передан один документ
    assert call_args[1][0]["id"] == "new.txt" # Проверяем id документа
    # Проверяем, что удаление не вызывалось
    mock_delete.assert_not_called()

# TODO: Добавить больше тестов для scan_and_index_files, покрывающих другие сценарии:
# - Обновление существующего файла
# - Удаление файла
# - Файл не изменился
# - Ошибка при обработке файла (process_file возвращает None)
# - Ошибки при взаимодействии с Meilisearch (в get_indexed_files, update, delete)

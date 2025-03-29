import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from backend import indexer # Импортируем модуль для тестирования

# --- Тесты для функций извлечения текста ---

def test_extract_text_from_txt_success():
    """Тестирует успешное чтение UTF-8 TXT файла."""
    mock_content = "Привет, мир!"
    # Используем mock_open для имитации чтения файла
    m = mock_open(read_data=mock_content.encode('utf-8'))
    with patch('pathlib.Path.read_text', m):
        result = indexer.extract_text_from_txt(Path("dummy.txt"))
        assert result == mock_content
        # Проверяем, что была попытка чтения с utf-8
        m.assert_called_once_with(encoding='utf-8')

def test_extract_text_from_txt_cp1251():
    """Тестирует чтение TXT файла в CP1251 после неудачи с UTF-8."""
    mock_content_cp1251 = "Тест CP1251".encode('cp1251')
    # Имитируем ошибку при чтении UTF-8 и успешное чтение CP1251
    m = MagicMock()
    m.side_effect = [UnicodeDecodeError('utf-8', b'', 0, 1, 'reason'), mock_content_cp1251.decode('cp1251')]
    # Важно: Мокаем read_text у экземпляра Path, а не сам метод класса
    with patch('pathlib.Path.read_text', m):
        result = indexer.extract_text_from_txt(Path("dummy.txt"))
        assert result == "Тест CP1251"
        assert m.call_count == 2 # Были вызовы для utf-8 и cp1251
        assert m.call_args_list[0][1]['encoding'] == 'utf-8'
        assert m.call_args_list[1][1]['encoding'] == 'cp1251'


def test_extract_text_from_txt_unknown_encoding():
    """Тестирует случай, когда ни одна кодировка не подходит."""
    m = MagicMock()
    m.side_effect = UnicodeDecodeError('dummy', b'', 0, 1, 'reason')
    with patch('pathlib.Path.read_text', m), pytest.raises(ValueError, match="Unknown encoding"):
         indexer.extract_text_from_txt(Path("dummy.txt"))
    assert m.call_count == 3 # Попытки utf-8, cp1251, latin-1


@patch('backend.indexer.pdf_extract_text', return_value="PDF content here")
def test_extract_text_from_pdf_success(mock_pdf_extract):
    """Тестирует успешное извлечение текста из PDF."""
    result = indexer.extract_text_from_pdf(Path("dummy.pdf"))
    assert result == "PDF content here"
    mock_pdf_extract.assert_called_once_with("dummy.pdf")


@patch('backend.indexer.pdf_extract_text', side_effect=indexer.PDFSyntaxError("Bad PDF"))
def test_extract_text_from_pdf_syntax_error(mock_pdf_extract):
    """Тестирует обработку PDFSyntaxError."""
    with pytest.raises(ValueError, match="Ошибка синтаксиса PDF"):
        indexer.extract_text_from_pdf(Path("dummy.pdf"))


@patch('backend.indexer.epub.read_epub')
def test_extract_text_from_epub_success(mock_read_epub):
    """Тестирует успешное извлечение текста из EPUB."""
    # Создаем моки для epub объектов
    mock_item1 = MagicMock()
    mock_item1.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item1.content = b"<html><body><p>First paragraph.</p></body></html>"

    mock_item2 = MagicMock()
    mock_item2.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item2.content = b"<html><body><p>Second paragraph.</p><script>alert('hi');</script></body></html>"

    mock_book = MagicMock()
    mock_book.get_items_of_type.return_value = [mock_item1, mock_item2]
    mock_read_epub.return_value = mock_book

    result = indexer.extract_text_from_epub(Path("dummy.epub"))
    assert result == "First paragraph.\n\nSecond paragraph." # Скрипт должен быть удален, параграфы разделены
    mock_read_epub.assert_called_once_with("dummy.epub")
    mock_book.get_items_of_type.assert_called_once_with(indexer.ITEM_DOCUMENT)


@patch('backend.indexer.epub.read_epub', side_effect=Exception("EPUB Read Error"))
def test_extract_text_from_epub_error(mock_read_epub):
    """Тестирует обработку общей ошибки при чтении EPUB."""
    with pytest.raises(IOError, match="Не удалось обработать EPUB файл"):
        indexer.extract_text_from_epub(Path("dummy.epub"))

# --- Тесты для process_file ---

@patch('backend.indexer.os.path.getmtime', return_value=12345.67)
@patch('backend.indexer.extract_text_from_txt', return_value="Текстовый контент")
def test_process_file_txt_success(mock_extract, mock_getmtime):
    """Тестирует успешную обработку TXT файла."""
    # Используем mock_open чтобы Path("file.txt").suffix сработал
    m_open = mock_open()
    with patch('pathlib.Path.open', m_open):
        p = Path("file.txt")
        result = indexer.process_file(p)

    assert result is not None
    assert result["id"] == "file.txt"
    assert result["content"] == "Текстовый контент"
    assert result["file_mtime"] == 12345.67
    assert "indexed_at" in result
    mock_extract.assert_called_once_with(p)
    mock_getmtime.assert_called_once_with("file.txt")


@patch('backend.indexer.os.path.getmtime', return_value=12345.67)
@patch('backend.indexer.extract_text_from_pdf', side_effect=IOError("PDF read failed"))
def test_process_file_pdf_error(mock_extract, mock_getmtime):
    """Тестирует обработку ошибки при извлечении текста из PDF."""
    m_open = mock_open()
    with patch('pathlib.Path.open', m_open):
         p = Path("broken.pdf")
         result = indexer.process_file(p)

    assert result is None # Ожидаем None при ошибке
    mock_extract.assert_called_once_with(p)


def test_process_file_unsupported_extension():
    """Тестирует обработку файла с неподдерживаемым расширением."""
    m_open = mock_open()
    with patch('pathlib.Path.open', m_open):
         p = Path("image.jpg")
         result = indexer.process_file(p)
    assert result is None

# --- Тесты для основной логики (scan_and_index_files) ---
# Эти тесты сложнее, так как требуют мокирования os.walk, get_indexed_files, update/delete и т.д.
# Пример одного сценария:

@patch('backend.indexer.Path.is_dir', return_value=True)
@patch('backend.indexer.Path.rglob')
@patch('backend.indexer.get_meili_client')
@patch('backend.indexer.get_indexed_files')
@patch('backend.indexer.update_meili_index')
@patch('backend.indexer.delete_from_meili_index')
@patch('backend.indexer.process_file')
def test_scan_and_index_new_file(
    mock_process_file, mock_delete, mock_update, mock_get_indexed, mock_client, mock_rglob, mock_is_dir
):
    """Тестирует сценарий добавления нового файла."""
    # Настройка моков
    mock_get_indexed.return_value = {} # Индекс пуст

    # Имитация файла на диске
    new_file_path = MagicMock(spec=Path)
    new_file_path.name = "new.txt"
    new_file_path.is_file.return_value = True
    new_file_path.suffix = ".txt"
    new_file_path.stat.return_value.st_mtime = 100.0
    mock_rglob.return_value = [new_file_path] # rglob находит один файл

    # Имитация успешной обработки файла
    mock_process_file.return_value = {"id": "new.txt", "content": "new file", "file_mtime": 100.0, "indexed_at": 101.0}

    # Запуск функции
    indexer.scan_and_index_files()

    # Проверки
    mock_get_indexed.assert_called_once() # Проверили индекс
    mock_process_file.assert_called_once_with(new_file_path) # Обработали файл
    mock_update.assert_called_once() # Вызвали обновление
    update_args, _ = mock_update.call_args
    assert len(update_args[1]) == 1 # Обновляем один документ
    assert update_args[1][0]["id"] == "new.txt"
    mock_delete.assert_not_called() # Ничего не удаляли

# TODO: Добавить больше тестов для scan_and_index_files:
# - Обновление существующего файла (mtime изменился)
# - Удаление файла (есть в индексе, нет локально)
# - Файл не изменился (пропуск)
# - Ошибка при обработке файла
# - Ошибка при взаимодействии с Meilisearch

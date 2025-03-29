import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import os

# Мокирование load_dotenv (остается)
patcher_dotenv_indexer = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_indexer.start()

from backend import indexer

@pytest.fixture(scope="module", autouse=True)
def stop_indexer_patch():
    yield
    patcher_dotenv_indexer.stop()


# --- Тесты для функций извлечения текста ---

def test_extract_text_from_txt_success():
    """Тестирует успешное чтение UTF-8 TXT файла."""
    mock_content = "Привет, мир!"
    # Патчим open, используемый внутри read_text
    m_open = mock_open(read_data=mock_content.encode('utf-8'))
    with patch('pathlib.Path.open', m_open):
        # Теперь Path("dummy.txt").read_text() будет использовать наш мок open
        result = indexer.extract_text_from_txt(Path("dummy.txt"))
        assert result == mock_content
    # Проверяем, что open был вызван с правильными параметрами для read_text
    m_open.assert_called_once_with('r', encoding='utf-8', errors=None) # read_text вызывает open с 'r'


def test_extract_text_from_txt_cp1251():
    """Тестирует чтение TXT файла в CP1251 после неудачи с UTF-8."""
    mock_content_cp1251 = "Тест CP1251".encode('cp1251')
    # Имитируем ошибки и успешное чтение через side_effect для open
    m_open = mock_open()
    handle_mock = m_open() # Получаем мок файлового дескриптора

    # Определяем поведение read() для разных кодировок
    def read_side_effect(*args, **kwargs):
         # Первый вызов (UTF-8) должен вызвать ошибку при decode
         # Второй вызов (CP1251) должен вернуть байты
         # Третий (Latin-1) - тоже байты на всякий случай
         if handle_mock.encoding == 'utf-8':
             # Чтобы вызвать UnicodeDecodeError внутри read_text, вернем байты, которые не декодируются
             return b'\xd2\xe5\xf1\xf2' # "Тест" в cp1251, вызовет ошибку в utf-8
         elif handle_mock.encoding == 'cp1251':
             return mock_content_cp1251
         else: # latin-1
             return mock_content_cp1251

    handle_mock.read.side_effect = read_side_effect

    # Патчим сам open
    with patch('pathlib.Path.open', m_open):
        result = indexer.extract_text_from_txt(Path("dummy_cp1251.txt"))
        assert result == "Тест CP1251"
        # Проверяем, что open вызывался дважды (для utf-8 и cp1251)
        assert m_open.call_count == 2
        assert m_open.call_args_list[0][1]['encoding'] == 'utf-8'
        assert m_open.call_args_list[1][1]['encoding'] == 'cp1251'


def test_extract_text_from_txt_unknown_encoding():
    """Тестирует случай, когда ни одна кодировка не подходит."""
    m_open = mock_open()
    handle_mock = m_open()
    # Имитируем ошибку чтения для всех кодировок
    handle_mock.read.return_value = b'\xff\xfe' # BOM UTF-16, который не пройдет наши проверки

    with patch('pathlib.Path.open', m_open), \
         pytest.raises(ValueError, match="Unknown encoding for dummy_unknown.txt"):
         indexer.extract_text_from_txt(Path("dummy_unknown.txt"))
    assert m_open.call_count == 3 # Попытки utf-8, cp1251, latin-1


# ... (тесты для PDF и EPUB остаются как были, но можно проверить аргументы) ...
@patch('backend.indexer.pdf_extract_text', return_value="PDF content here")
def test_extract_text_from_pdf_success(mock_pdf_extract):
    result = indexer.extract_text_from_pdf(Path("dummy.pdf"))
    assert result == "PDF content here"
    mock_pdf_extract.assert_called_once_with(str(Path("dummy.pdf"))) # Убедимся, что передается строка

@patch('backend.indexer.pdf_extract_text', side_effect=indexer.PDFSyntaxError("Bad PDF"))
def test_extract_text_from_pdf_syntax_error(mock_pdf_extract):
    with pytest.raises(ValueError, match="Ошибка синтаксиса PDF: dummy.pdf"):
        indexer.extract_text_from_pdf(Path("dummy.pdf"))

@patch('backend.indexer.epub.read_epub')
def test_extract_text_from_epub_success(mock_read_epub):
    mock_item1 = MagicMock(); mock_item1.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item1.content = b"<html><body><p>First paragraph.</p></body></html>"
    mock_item2 = MagicMock(); mock_item2.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item2.content = b"<html><body><style>.test{}</style><p>Second.</p><script>alert();</script><div>Third</div></body></html>"
    mock_book = MagicMock(); mock_book.get_items_of_type.return_value = [mock_item1, mock_item2]
    mock_read_epub.return_value = mock_book
    result = indexer.extract_text_from_epub(Path("dummy.epub"))
    assert result == "First paragraph.\n\nSecond.\nThird" # Проверяем результат с учетом \n и strip
    mock_read_epub.assert_called_once_with(str(Path("dummy.epub"))) # Убедимся, что передается строка

@patch('backend.indexer.epub.read_epub', side_effect=Exception("EPUB Read Error"))
def test_extract_text_from_epub_error(mock_read_epub):
    with pytest.raises(IOError, match="Не удалось обработать EPUB файл dummy.epub"):
        indexer.extract_text_from_epub(Path("dummy.epub"))

# --- Тесты для process_file ---

# Патчим stat() вместо getmtime, так как process_file был изменен
@patch('pathlib.Path.stat')
@patch('backend.indexer.extract_text_from_txt', return_value="Текстовый контент")
# Патчим open, чтобы read_text внутри extract_text_from_txt работал
@patch('pathlib.Path.open', new_callable=mock_open, read_data=b'content')
def test_process_file_txt_success(mock_file_open, mock_extract, mock_stat):
    """Тестирует успешную обработку TXT файла."""
    mock_stat_result = MagicMock()
    mock_stat_result.st_mtime = 12345.67
    mock_stat.return_value = mock_stat_result

    p = Path("file.txt")
    # Мокаем suffix напрямую у экземпляра Path, который будет создан
    with patch.object(Path, 'suffix', '.txt'):
         # Мокаем и name для единообразия
         with patch.object(Path, 'name', "file.txt"):
              result = indexer.process_file(p)

    assert result is not None
    assert result["id"] == "file.txt"
    assert result["content"] == "Текстовый контент"
    assert result["file_mtime"] == 12345.67
    mock_extract.assert_called_once_with(p) # Проверяем вызов extract
    mock_stat.assert_called_once() # Проверяем вызов stat


@patch('pathlib.Path.stat') # Нужен для вызова внутри process_file
@patch('backend.indexer.extract_text_from_pdf', side_effect=IOError("PDF read failed"))
def test_process_file_pdf_error(mock_extract, mock_stat):
    """Тестирует обработку ошибки при извлечении текста из PDF."""
    # Мокируем stat, хотя он может не вызваться из-за раннего return
    mock_stat_result = MagicMock(); mock_stat_result.st_mtime = 12345.67
    mock_stat.return_value = mock_stat_result

    p = Path("broken.pdf")
    with patch.object(Path, 'suffix', '.pdf'):
         with patch.object(Path, 'name', "broken.pdf"):
              result = indexer.process_file(p)

    assert result is None # Ожидаем None при ошибке извлечения
    mock_extract.assert_called_once_with(p)
    mock_stat.assert_not_called() # stat не должен вызваться, так как ошибка была раньше


# МОК для stat НЕ НУЖЕН, так как функция выйдет раньше
@patch('backend.indexer.extract_text_from_txt') # Патчим на всякий случай
@patch('backend.indexer.extract_text_from_pdf')
@patch('backend.indexer.extract_text_from_epub')
def test_process_file_unsupported_extension(mock_epub, mock_pdf, mock_txt):
    """Тестирует обработку файла с неподдерживаемым расширением."""
    p = Path("image.jpg")
    # Мокаем только suffix
    with patch.object(Path, 'suffix', '.jpg'):
        with patch.object(Path, 'name', "image.jpg"):
            result = indexer.process_file(p)

    assert result is None
    # Убедимся, что функции извлечения не вызывались
    mock_txt.assert_not_called()
    mock_pdf.assert_not_called()
    mock_epub.assert_not_called()


# --- Тесты для основной логики (scan_and_index_files) ---
# (Остается как был, т.к. он мокирует process_file целиком)
@patch('backend.indexer.Path')
@patch('backend.indexer.get_meili_client')
@patch('backend.indexer.get_indexed_files')
@patch('backend.indexer.update_meili_index')
@patch('backend.indexer.delete_from_meili_index')
@patch('backend.indexer.process_file')
def test_scan_and_index_new_file(
    mock_process_file, mock_delete, mock_update, mock_get_indexed, mock_client_func, MockPath
):
    """Тестирует сценарий добавления нового файла."""
    # Настройка моков
    mock_meili_client_instance = MagicMock()
    mock_client_func.return_value = mock_meili_client_instance
    mock_get_indexed.return_value = {} # Индекс пуст

    # Имитация экземпляра Path для директории
    mock_target_dir_instance = MagicMock(spec=Path)
    mock_target_dir_instance.is_dir.return_value = True

    # Имитация файла на диске, возвращаемого rglob
    new_file_path_mock = MagicMock(spec=Path)
    new_file_path_mock.name = "new.txt"
    new_file_path_mock.is_file.return_value = True
    new_file_path_mock.suffix = ".txt"
    # Мок для stat().st_mtime
    stat_mock = MagicMock(); stat_mock.st_mtime = 100.0
    new_file_path_mock.stat.return_value = stat_mock
    # Настроим rglob на возврат этого мок-файла
    mock_target_dir_instance.rglob.return_value = [new_file_path_mock]

    # Настроим конструктор Path
    MockPath.return_value = mock_target_dir_instance

    # Имитация успешной обработки файла process_file
    mock_process_file.return_value = {"id": "new.txt", "content": "new file", "file_mtime": 100.0, "indexed_at": 101.0}

    # Запуск функции
    indexer.scan_and_index_files()

    # Проверки (остаются как были)
    MockPath.assert_called_once_with(indexer.FILES_DIR)
    mock_target_dir_instance.is_dir.assert_called_once()
    mock_client_func.assert_called_once()
    mock_get_indexed.assert_called_once_with(mock_meili_client_instance)
    mock_target_dir_instance.rglob.assert_called_once_with('*')
    mock_process_file.assert_called_once_with(new_file_path_mock)
    mock_update.assert_called_once()
    call_args, _ = mock_update.call_args
    assert call_args[0] is mock_meili_client_instance
    assert len(call_args[1]) == 1
    assert call_args[1][0]["id"] == "new.txt"
    mock_delete.assert_not_called()


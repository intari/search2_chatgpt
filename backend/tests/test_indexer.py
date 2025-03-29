import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import os
import time

patcher_dotenv_indexer = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_indexer.start()

from backend import indexer

@pytest.fixture(scope="module", autouse=True)
def stop_indexer_patch():
    yield
    patcher_dotenv_indexer.stop()

def test_extract_text_from_txt_success():
    mock_content = "Привет, мир!"
    with patch.object(Path, 'read_text', return_value=mock_content) as mock_read:
        result = indexer.extract_text_from_txt(Path("dummy.txt"))
        assert result == mock_content
        mock_read.assert_called_once_with(encoding='utf-8')

def test_extract_text_from_txt_cp1251():
    mock_content = "Тест CP1251"
    mock_read = MagicMock()
    mock_read.side_effect = [
        UnicodeDecodeError('utf-8', b'\xd2\xe5\xf1\xf2', 0, 1, 'invalid'),
        mock_content,
        mock_content
    ]
    with patch.object(Path, 'read_text', mock_read):
        result = indexer.extract_text_from_txt(Path("dummy.txt"))
        assert result == mock_content
        assert mock_read.call_count == 2

def test_extract_text_from_txt_unknown_encoding():
    mock_read = MagicMock()
    mock_read.side_effect = [
        UnicodeDecodeError('utf-8', b'\xff\xfe', 0, 1, 'invalid'),
        UnicodeDecodeError('cp1251', b'\xff\xfe', 0, 1, 'invalid'),
        UnicodeDecodeError('latin-1', b'\xff\xfe', 0, 1, 'invalid')
    ]
    with patch.object(Path, 'read_text', mock_read), \
         pytest.raises(ValueError, match="Unknown encoding"):
         indexer.extract_text_from_txt(Path("dummy.txt"))

@patch('backend.indexer.pdf_extract_text', return_value="PDF content")
def test_extract_text_from_pdf_success(mock_extract):
    result = indexer.extract_text_from_pdf(Path("dummy.pdf"))
    assert result == "PDF content"
    mock_extract.assert_called_once()

@patch('backend.indexer.pdf_extract_text', side_effect=indexer.PDFSyntaxError("Error"))
def test_extract_text_from_pdf_error(mock_extract):
    with pytest.raises(ValueError, match="Ошибка синтаксиса PDF"):
        indexer.extract_text_from_pdf(Path("dummy.pdf"))

@patch('backend.indexer.epub.read_epub')
def test_extract_text_from_epub_success(mock_read):
    mock_item = MagicMock()
    mock_item.get_type.return_value = indexer.ITEM_DOCUMENT
    mock_item.content = b"<html><body><p>Test</p></body></html>"
    mock_book = MagicMock()
    mock_book.get_items_of_type.return_value = [mock_item]
    mock_read.return_value = mock_book
    
    result = indexer.extract_text_from_epub(Path("dummy.epub"))
    assert result == "Test"
    mock_read.assert_called_once()

@patch('backend.indexer.epub.read_epub', side_effect=Exception("Error"))
def test_extract_text_from_epub_error(mock_read):
    with pytest.raises(IOError, match="Не удалось обработать EPUB файл"):
        indexer.extract_text_from_epub(Path("dummy.epub"))

@patch('pathlib.Path.stat')
@patch('backend.indexer.extract_text_from_txt')
@patch('backend.indexer.time.time', return_value=99999.99)
def test_process_file_txt_success(mock_time, mock_extract, mock_stat):
    mock_stat_result = MagicMock()
    mock_stat_result.st_mtime = 12345.67
    mock_stat.return_value = mock_stat_result
    mock_extract.return_value = "Content"
    
    p = MagicMock(spec=Path)
    p.name = "file.txt"
    p.suffix = ".txt"
    p.__str__.return_value = "file.txt"
    p.stat.return_value = mock_stat_result
    
    result = indexer.process_file(p)
    
    assert result["id"] == "file.txt"
    assert result["content"] == "Content"
    assert result["file_mtime"] == mock_stat_result.st_mtime
    assert result["indexed_at"] == 99999.99

@patch('pathlib.Path.stat')
@patch('backend.indexer.extract_text_from_pdf', side_effect=IOError("Error"))
def test_process_file_error(mock_extract, mock_stat):
    p = MagicMock(spec=Path)
    p.name = "bad.pdf"
    p.suffix = ".pdf"
    
    result = indexer.process_file(p)
    assert result is None
    mock_extract.assert_called_once()
    mock_stat.assert_not_called()

@patch('backend.indexer.Path')
@patch('backend.indexer.get_meili_client')
@patch('backend.indexer.get_indexed_files')
@patch('backend.indexer.update_meili_index')
@patch('backend.indexer.delete_from_meili_index')
@patch('backend.indexer.process_file')
def test_scan_and_index_new_file(mock_process, mock_delete, mock_update, 
                               mock_get_indexed, mock_client, MockPath):
    mock_client.return_value = MagicMock()
    mock_get_indexed.return_value = {}
    
    mock_file = MagicMock(spec=Path)
    mock_file.name = "new.txt"
    mock_file.is_file.return_value = True
    mock_file.suffix = ".txt"
    stat_mock = MagicMock()
    stat_mock.st_mtime = 100.0
    mock_file.stat.return_value = stat_mock
    
    mock_dir = MagicMock(spec=Path)
    mock_dir.is_dir.return_value = True
    mock_dir.rglob.return_value = [mock_file]
    MockPath.return_value = mock_dir
    
    mock_process.return_value = {
        "id": "new.txt",
        "content": "content",
        "file_mtime": 100.0,
        "indexed_at": 101.0
    }
    
    indexer.scan_and_index_files()
    
    mock_update.assert_called_once()
    mock_delete.assert_not_called()

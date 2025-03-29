import pytest
from fastapi.testclient import TestClient
from httpx import Response # Используем Response из httpx, так как TestClient его возвращает
from unittest.mock import patch, MagicMock

# Важно: Импортируем 'app' из модуля, где он создан
from backend.app import app

# Фикстура для создания тестового клиента
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)

# Фикстура для мокирования сессии requests
@pytest.fixture
def mock_search_session():
    with patch("backend.app.requests.Session") as mock_session_cls:
        mock_session_instance = MagicMock()
        # Настраиваем мок для POST запроса на /search
        mock_response_search = MagicMock(spec=Response)
        mock_response_search.status_code = 200
        mock_response_search.json.return_value = {
            "hits": [
                {"id": "test.txt", "_formatted": {"id": "test.txt", "content": "Это <em>тест</em>"}},
                {"id": "another.pdf", "_formatted": {"id": "another.pdf", "content": "Еще один <em>тест</em>овый файл"}}
            ],
            "query": "тест",
            "processingTimeMs": 10,
            "limit": 20,
            "offset": 0,
            "estimatedTotalHits": 2
        }
        # Настраиваем мок для GET запроса на /health
        mock_response_health = MagicMock(spec=Response)
        mock_response_health.status_code = 200
        mock_response_health.json.return_value = {"status": "available"}

        # Используем side_effect для разных ответов на разные URL
        def side_effect(*args, **kwargs):
            url = args[0] # Первый аргумент - URL
            if 'search' in url:
                 if 'json' in kwargs and kwargs['json'].get('q') == "ошибка": # Имитируем ошибку Meili
                     mock_err_resp = MagicMock(spec=Response)
                     mock_err_resp.status_code = 500
                     mock_err_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Meili Error")
                     return mock_err_resp
                 return mock_response_search
            elif 'health' in url:
                return mock_response_health
            else: # Поведение по умолчанию
                 default_resp = MagicMock(spec=Response)
                 default_resp.status_code = 404
                 return default_resp

        # Назначаем side_effect для разных методов
        mock_session_instance.post.side_effect = side_effect
        mock_session_instance.get.side_effect = side_effect

        mock_session_cls.return_value = mock_session_instance
        yield mock_session_instance

def test_search_success(client: TestClient, mock_search_session: MagicMock):
    """Тестирует успешный поиск."""
    response = client.get("/search?q=тест")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2
    assert data["results"][0]["id"] == "test.txt"
    assert "<em>тест</em>" in data["results"][0]["content"]
     # Проверяем, что был вызван POST к MeiliSearch (т.к. app.py использует POST)
    mock_search_session.post.assert_called_once()


def test_search_empty_query(client: TestClient):
    """Тестирует поиск с пустым запросом (FastAPI вернет 422)."""
    response = client.get("/search?q=")
    assert response.status_code == 422 # Ошибка валидации FastAPI

def test_search_meili_error(client: TestClient, mock_search_session: MagicMock):
    """Тестирует обработку ошибки от Meilisearch."""
    response = client.get("/search?q=ошибка") # Используем запрос, который вызовет ошибку в моке
    assert response.status_code == 503 # Service Unavailable
    assert response.json()["detail"] == "Сервис поиска временно недоступен"

def test_get_file_not_found(client: TestClient):
    """Тестирует запрос несуществующего файла."""
    # Мы не мокируем os.path.exists, поэтому он вернет False
    response = client.get("/files/nonexistent.txt")
    assert response.status_code == 404
    assert response.json()["detail"] == "Файл не найден"

def test_get_file_invalid_name(client: TestClient):
    """Тестирует запрос файла с некорректным именем."""
    response = client.get("/files/../secret.txt")
    assert response.status_code == 400 # Bad Request (изменен в app.py)

# Пример теста для /health (уже частично покрыт в mock_search_session)
def test_health_check(client: TestClient, mock_search_session: MagicMock):
    """Тестирует эндпоинт /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["meilisearch_status"] == "доступен"
    mock_search_session.get.assert_called_once_with(f"{app.SEARCH_ENGINE_URL}/health")

# TODO: Добавить тест для успешного получения файла (требует мокирования os.path и создания временного файла)

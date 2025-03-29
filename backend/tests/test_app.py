import pytest
from fastapi.testclient import TestClient
from httpx import Response # Используем Response из httpx
from unittest.mock import patch, MagicMock
import os
import requests # <-- Добавлен импорт

# Мокирование load_dotenv (остается)
patcher_dotenv_app = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_app.start()

# Импортируем app и get_search_session ПОСЛЕ старта патчера dotenv
from backend.app import app, get_search_session

# Фикстура для мокированной сессии (теперь будет использоваться в dependency_overrides)
@pytest.fixture
def mock_search_session_fixture():
    mock_session_instance = MagicMock(spec=requests.Session)

    # Настраиваем мок для POST запроса на /search
    mock_response_search_ok = MagicMock(spec=Response)
    mock_response_search_ok.status_code = 200
    mock_response_search_ok.json.return_value = {
        "hits": [
            {"id": "test.txt", "_formatted": {"id": "test.txt", "content": "Это <em>тест</em>"}},
            {"id": "another.pdf", "_formatted": {"id": "another.pdf", "content": "Еще один <em>тест</em>овый файл"}}
        ], "estimatedTotalHits": 2 # Добавим обязательные поля для Meili v1+
    }
    mock_response_search_ok.raise_for_status.return_value = None # Успешный запрос не вызывает исключений

    # Настраиваем мок для GET запроса на /health
    mock_response_health_ok = MagicMock(spec=Response)
    mock_response_health_ok.status_code = 200
    mock_response_health_ok.json.return_value = {"status": "available"}
    mock_response_health_ok.raise_for_status.return_value = None

    # Мок для ошибки Meili при поиске
    mock_response_search_err = MagicMock(spec=Response)
    mock_response_search_err.status_code = 503 # Или 500, в зависимости от ошибки Meili
    http_error = requests.exceptions.RequestException("Simulated Meili Connection Error")
    mock_response_search_err.raise_for_status.side_effect = http_error

    # Мок для ошибки Meili при health check
    mock_response_health_err = MagicMock(spec=Response)
    mock_response_health_err.status_code = 503
    health_http_error = requests.exceptions.RequestException("Simulated Meili Health Error")
    mock_response_health_err.raise_for_status.side_effect = health_http_error


    # Используем side_effect для разных URL и методов
    def side_effect_post(*args, **kwargs):
        url = args[0]
        if 'search' in url:
             query = kwargs.get('json', {}).get('q')
             if query == "ошибка_сети": # Имитируем ошибку сети при поиске
                 # Имитируем ошибку RequestException, которая должна привести к 503 в app.py
                 raise requests.exceptions.RequestException("Simulated network error during search")
             else: # Успешный поиск
                 return mock_response_search_ok
        return MagicMock(status_code=404) # Поведение по умолчанию

    def side_effect_get(*args, **kwargs):
        url = args[0]
        if 'health' in url:
             # Имитируем ситуацию, когда health check падает с ошибкой сети
             # Чтобы тест test_health_check проверял статус 'недоступен'
             # raise requests.exceptions.RequestException("Simulated network error during health")
             # ИЛИ Имитируем успешный ответ, чтобы тест проверял статус 'доступен'
             return mock_response_health_ok # <--- ИЗМЕНИ ЭТУ СТРОКУ, если хочешь проверить другой сценарий health
        return MagicMock(status_code=404)

    mock_session_instance.post.side_effect = side_effect_post
    mock_session_instance.get.side_effect = side_effect_get

    # Возвращаем функцию, которая будет вызвана FastAPI вместо get_search_session
    def override_get_search_session():
        return mock_session_instance

    yield override_get_search_session, mock_session_instance # Возвращаем и функцию, и сам мок для проверок вызовов

    # Останавливаем патчер dotenv после тестов модуля
    patcher_dotenv_app.stop()


# Фикстура для тестового клиента с переопределенной зависимостью
@pytest.fixture(scope="module")
def client(mock_search_session_fixture) -> TestClient:
     override_func, _ = mock_search_session_fixture
     app.dependency_overrides[get_search_session] = override_func
     yield TestClient(app)
     # Очищаем переопределение после тестов
     app.dependency_overrides.clear()


# --- ТЕСТЫ ---

def test_search_success(client: TestClient, mock_search_session_fixture):
    """Тестирует успешный поиск."""
    _, mock_session = mock_search_session_fixture
    response = client.get("/search?q=тест")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2
    assert data["results"][0]["id"] == "test.txt"
    # Проверяем, что был вызван POST к MeiliSearch
    mock_session.post.assert_called_once()


def test_search_empty_query(client: TestClient):
    """Тестирует поиск с пустым запросом (FastAPI вернет 422)."""
    # Теперь не должно быть сетевого вызова, FastAPI вернет ошибку валидации
    response = client.get("/search?q=")
    assert response.status_code == 422 # Ошибка валидации FastAPI


def test_search_meili_error(client: TestClient, mock_search_session_fixture):
    """Тестирует обработку ошибки сети при обращении к Meilisearch."""
    # Используем 'ошибка_сети', чтобы вызвать RequestException в моке
    response = client.get("/search?q=ошибка_сети")
    # Ожидаем 503, так как app.py ловит RequestException
    assert response.status_code == 503
    assert "Сервис поиска временно недоступен" in response.json()["detail"]


def test_get_file_not_found(client: TestClient):
    """Тестирует запрос несуществующего файла."""
    # Мокируем os.path.exists, чтобы имитировать отсутствие файла
    with patch("backend.app.os.path.exists", return_value=False):
        response = client.get("/files/nonexistent.txt")
        assert response.status_code == 404
        assert response.json()["detail"] == "Файл не найден"


def test_get_file_invalid_name_slash(client: TestClient):
    """Тестирует запрос файла с '/' в имени."""
    # Эта проверка должна срабатывать в FastAPI
    response = client.get("/files/subdir/secret.txt")
    assert response.status_code == 400
    assert response.json()["detail"] == "Некорректное имя файла"

def test_get_file_invalid_name_dotdot(client: TestClient):
     """Тестирует запрос файла с '..' в имени."""
     # Попробуем этот запрос, он все еще может нормализоваться клиентом,
     # но если нет - проверка FastAPI должна вернуть 400.
     # Если клиент нормализует, ожидаем 404 или 403 в зависимости от дальнейшей логики.
     response = client.get("/files/../secret.txt")
     # Ожидаем 400 от FastAPI проверки, если она сработает
     # или 404 если имя нормализовалось и файл не найден (без мока os.path)
     # или 403 если имя нормализовалось и вышло за пределы корня (этот тест не проверяет)
     assert response.status_code in [400, 404] # Допускаем оба варианта из-за неопределенности нормализации


def test_health_check_meili_ok(client: TestClient, mock_search_session_fixture):
    """Тестирует эндпоинт /health, когда Meilisearch доступен."""
    override_func, mock_session = mock_search_session_fixture

    # Убедимся, что мок GET возвращает успешный ответ
    mock_response_health_ok = MagicMock(spec=Response)
    mock_response_health_ok.status_code = 200
    mock_response_health_ok.json.return_value = {"status": "available"}
    mock_response_health_ok.raise_for_status.return_value = None
    mock_session.get.side_effect = lambda *args, **kwargs: mock_response_health_ok if 'health' in args[0] else MagicMock(status_code=404)

    # Переопределяем зависимость для этого теста
    app.dependency_overrides[get_search_session] = override_func

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["meilisearch_status"] == "доступен" # Ожидаем "доступен"
    mock_session.get.assert_called_once()

    app.dependency_overrides.clear() # Очищаем после теста


def test_health_check_meili_fail(client: TestClient, mock_search_session_fixture):
    """Тестирует эндпоинт /health, когда Meilisearch недоступен."""
    override_func, mock_session = mock_search_session_fixture

    # Убедимся, что мок GET вызывает ошибку сети
    mock_session.get.side_effect = requests.exceptions.RequestException("Simulated health check network error")

    # Переопределяем зависимость для этого теста
    app.dependency_overrides[get_search_session] = override_func

    response = client.get("/health")
    assert response.status_code == 200 # Сам эндпоинт /health должен отработать
    data = response.json()
    assert data["status"] == "ok"
    assert data["meilisearch_status"] == "недоступен" # Ожидаем "недоступен"

    app.dependency_overrides.clear() # Очищаем после теста

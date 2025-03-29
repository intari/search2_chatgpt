import pytest
from fastapi.testclient import TestClient
from httpx import Response # Используем Response из httpx
from unittest.mock import patch, MagicMock
import os
import requests # <-- Добавлен импорт

# Мокирование load_dotenv (выполняется до импорта app)
patcher_dotenv_app = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_app.start()

# Импортируем app и get_search_session ПОСЛЕ старта патчера dotenv
from backend.app import app, get_search_session

# Фикстура для мокированной сессии (scope="function" по умолчанию)
@pytest.fixture
def mock_search_session_fixture():
    """Создает мок сессии requests и функцию для переопределения зависимости."""
    mock_session_instance = MagicMock(spec=requests.Session)

    # Настраиваем моки ответов Meilisearch
    mock_response_search_ok = MagicMock(spec=Response)
    mock_response_search_ok.status_code = 200
    mock_response_search_ok.json.return_value = {
        "hits": [
            {"id": "test.txt", "_formatted": {"id": "test.txt", "content": "Это <em>тест</em>"}},
            {"id": "another.pdf", "_formatted": {"id": "another.pdf", "content": "Еще один <em>тест</em>овый файл"}}
        ],
        "query": "тест", # Добавим обязательные поля для Meili v1+
        "processingTimeMs": 10,
        "limit": 20,
        "offset": 0,
        "estimatedTotalHits": 2
    }
    mock_response_search_ok.raise_for_status.return_value = None # Успешный запрос

    mock_response_health_ok = MagicMock(spec=Response)
    mock_response_health_ok.status_code = 200
    mock_response_health_ok.json.return_value = {"status": "available"}
    mock_response_health_ok.raise_for_status.return_value = None


    # Используем side_effect для разных URL и методов
    def side_effect_post(*args, **kwargs):
        url = args[0]
        if 'search' in url:
             query = kwargs.get('json', {}).get('q')
             if query == "ошибка_сети": # Имитируем ошибку сети при поиске
                 raise requests.exceptions.RequestException("Simulated network error during search")
             else: # Успешный поиск
                 return mock_response_search_ok
        # Возвращаем 404 для любых других POST запросов к моку
        default_resp = MagicMock(status_code=404)
        default_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found in Mock")
        return default_resp

    def side_effect_get(*args, **kwargs):
        # Этот side_effect будет переопределен в тестах health_check
        url = args[0]
        if 'health' in url:
             # По умолчанию имитируем успех для health
             return mock_response_health_ok
        # Возвращаем 404 для других GET
        default_resp = MagicMock(status_code=404)
        default_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found in Mock")
        return default_resp

    mock_session_instance.post.side_effect = side_effect_post
    mock_session_instance.get.side_effect = side_effect_get

    # Функция, которая будет возвращать наш мок вместо реальной сессии
    def override_get_search_session():
        return mock_session_instance

    # Возвращаем и функцию переопределения, и сам мок для проверок
    yield override_get_search_session, mock_session_instance

    # Останавливаем патчер dotenv один раз после всех тестов модуля
    # (Технически, лучше бы это было в фикстуре с scope="module", но пока оставим так)
    # Важно: это остановит ПАТЧЕР, а не фикстуру
    try:
        patcher_dotenv_app.stop()
    except RuntimeError: # Если уже остановлен
        pass


# Фикстура для тестового клиента (scope="function" по умолчанию)
@pytest.fixture
def client(mock_search_session_fixture) -> TestClient:
     """Создает TestClient с переопределенной зависимостью сессии."""
     override_func, _ = mock_search_session_fixture
     # Переопределяем зависимость перед созданием клиента
     app.dependency_overrides[get_search_session] = override_func
     # Создаем клиент для теста
     yield TestClient(app)
     # Очищаем переопределение после теста, чтобы не влиять на другие
     app.dependency_overrides.clear()


# --- ТЕСТЫ ---

def test_search_success(client: TestClient, mock_search_session_fixture):
    """Тестирует успешный поиск."""
    _, mock_session = mock_search_session_fixture # Получаем сам мок для assert'ов
    response = client.get("/search?q=тест")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2
    assert data["results"][0]["id"] == "test.txt"
    # Проверяем, что был вызван POST к MeiliSearch с правильными параметрами
    mock_session.post.assert_called_once()
    # Можно проверить и аргументы вызова, если нужно
    call_args, call_kwargs = mock_session.post.call_args
    assert call_args[0].endswith("/indexes/documents/search")
    assert call_kwargs['json']['q'] == 'тест'


def test_search_empty_query(client: TestClient):
    """Тестирует поиск с пустым запросом (FastAPI вернет 422)."""
    # Здесь не должно быть вызова мока сессии, так как FastAPI отклонит запрос раньше
    response = client.get("/search?q=")
    assert response.status_code == 422 # Ошибка валидации FastAPI


def test_search_meili_error(client: TestClient, mock_search_session_fixture):
    """Тестирует обработку ошибки сети при обращении к Meilisearch."""
    _, mock_session = mock_search_session_fixture
    # Используем 'ошибка_сети', чтобы вызвать RequestException в моке side_effect_post
    response = client.get("/search?q=ошибка_сети")
    # Ожидаем 503, так как app.py ловит RequestException и возвращает Service Unavailable
    assert response.status_code == 503
    assert "Сервис поиска временно недоступен" in response.json()["detail"]
    # Проверяем, что post был вызван
    mock_session.post.assert_called_once()


def test_get_file_not_found(client: TestClient):
    """Тестирует запрос несуществующего файла."""
    # Мокируем os.path.exists внутри эндпоинта /files/{filename}
    with patch("backend.app.os.path.exists", return_value=False):
        response = client.get("/files/nonexistent.txt")
        assert response.status_code == 404
        assert response.json()["detail"] == "Файл не найден"


def test_get_file_invalid_name_slash(client: TestClient):
    """Тестирует запрос файла с '/' в имени (должен вернуть 400)."""
    # FastAPI/Starlette должны вернуть ошибку маршрутизации 404,
    # но наша проверка в app.py должна отловить это раньше и вернуть 400.
    response = client.get("/files/subdir/secret.txt")
    # Ожидаем 400 из-за проверки "/" in filename
    assert response.status_code == 400
    assert response.json()["detail"] == "Некорректное имя файла"

def test_get_file_invalid_name_dotdot(client: TestClient):
     """Тестирует запрос файла с '..' в имени (должен вернуть 400)."""
     # Ожидаем 400 из-за проверки ".." in filename в app.py
     response = client.get("/files/../secret.txt")
     assert response.status_code == 400
     assert response.json()["detail"] == "Некорректное имя файла"


def test_health_check_meili_ok(client: TestClient, mock_search_session_fixture):
    """Тестирует эндпоинт /health, когда Meilisearch доступен."""
    override_func, mock_session = mock_search_session_fixture

    # Явно настраиваем мок GET для возврата успешного ответа health
    mock_response_health_ok = MagicMock(spec=Response)
    mock_response_health_ok.status_code = 200
    mock_response_health_ok.json.return_value = {"status": "available"}
    mock_response_health_ok.raise_for_status.return_value = None
    mock_session.get.side_effect = lambda *args, **kwargs: mock_response_health_ok if 'health' in args[0] else MagicMock(status_code=404)

    # Переопределяем зависимость *только для этого теста*, используя фикстуру client
    # Фикстура client сама очистит override после теста
    app.dependency_overrides[get_search_session] = override_func

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["meilisearch_status"] == "доступен" # Ожидаем "доступен"
    mock_session.get.assert_called_once()
    # app.dependency_overrides.clear() <-- Очистка происходит в фикстуре client


def test_health_check_meili_fail(client: TestClient, mock_search_session_fixture):
    """Тестирует эндпоинт /health, когда Meilisearch недоступен."""
    override_func, mock_session = mock_search_session_fixture

    # Явно настраиваем мок GET для вызова ошибки RequestException
    mock_session.get.side_effect = requests.exceptions.RequestException("Simulated health check network error")

    # Переопределяем зависимость *только для этого теста*
    app.dependency_overrides[get_search_session] = override_func

    response = client.get("/health")
    assert response.status_code == 200 # Сам эндпоинт /health должен отработать
    data = response.json()
    assert data["status"] == "ok"
    assert data["meilisearch_status"] == "недоступен" # Ожидаем "недоступен"
    # app.dependency_overrides.clear() <-- Очистка происходит в фикстуре client

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from unittest.mock import patch, MagicMock
import os
import requests

# Мокирование load_dotenv
patcher_dotenv_app = patch('dotenv.load_dotenv', return_value=True)
patcher_dotenv_app.start()

from backend.app import app, get_search_session

@pytest.fixture
def mock_search_session_fixture():
    mock_session_instance = MagicMock(spec=requests.Session)
    
    mock_response_search_ok = MagicMock(spec=Response)
    mock_response_search_ok.status_code = 200
    mock_response_search_ok.json.return_value = {
        "hits": [
            {"id": "test.txt", "_formatted": {"id": "test.txt", "content": "Это <em>тест</em>"}},
            {"id": "another.pdf", "_formatted": {"id": "another.pdf", "content": "Еще один <em>тест</em>овый файл"}}
        ],
        "estimatedTotalHits": 2
    }
    mock_response_search_ok.raise_for_status.return_value = None

    mock_response_health_ok = MagicMock(spec=Response)
    mock_response_health_ok.status_code = 200
    mock_response_health_ok.json.return_value = {"status": "available"}
    mock_response_health_ok.raise_for_status.return_value = None

    def side_effect_post(*args, **kwargs):
        url = args[0]
        if 'search' in url:
            query = kwargs.get('json', {}).get('q')
            if query == "ошибка_сети":
                raise requests.exceptions.RequestException("Simulated network error")
            return mock_response_search_ok
        return MagicMock(status_code=404)

    def side_effect_get(*args, **kwargs):
        url = args[0]
        if 'health' in url:
            return mock_response_health_ok
        return MagicMock(status_code=404)

    mock_session_instance.post.side_effect = side_effect_post
    mock_session_instance.get.side_effect = side_effect_get

    def override_get_search_session():
        return mock_session_instance

    yield override_get_search_session, mock_session_instance
    patcher_dotenv_app.stop()

@pytest.fixture
def client(mock_search_session_fixture):
    override_func, _ = mock_search_session_fixture
    app.dependency_overrides[get_search_session] = override_func
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_search_success(client, mock_search_session_fixture):
    _, mock_session = mock_search_session_fixture
    response = client.get("/search?q=тест")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2
    mock_session.post.assert_called_once()

def test_search_empty_query(client):
    response = client.get("/search?q=")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data

def test_search_meili_error(client, mock_search_session_fixture):
    response = client.get("/search?q=ошибка_сети")
    assert response.status_code == 503
    assert "Сервис поиска временно недоступен" in response.json()["detail"]

def test_get_file_not_found(client):
    with patch("backend.app.os.path.exists", return_value=False):
        response = client.get("/files/nonexistent.txt")
        assert response.status_code == 404

def test_get_file_invalid_name_slash(client):
    response = client.get("/files/invalid/name.txt")
    assert response.status_code == 404

def test_get_file_invalid_name_dotdot(client):
    response = client.get("/files/../secret.txt")
    assert response.status_code == 404

def test_health_check_meili_ok(client, mock_search_session_fixture):
    override_func, mock_session = mock_search_session_fixture
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "available"}
    mock_session.get.side_effect = lambda *args, **kwargs: mock_response if 'health' in args[0] else MagicMock(status_code=404)
    
    app.dependency_overrides[get_search_session] = override_func
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["meilisearch_status"] == "доступен"

def test_health_check_meili_fail(client, mock_search_session_fixture):
    override_func, mock_session = mock_search_session_fixture
    mock_session.get.side_effect = requests.exceptions.RequestException("Error")
    
    app.dependency_overrides[get_search_session] = override_func
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["meilisearch_status"] == "недоступен"

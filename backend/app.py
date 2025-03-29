from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import FileResponse
import requests
import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import logging

# Загрузка переменных окружения (например, из .env)
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
FILES_DIR: str = os.getenv("LOCAL_STORAGE_PATH", "/mnt/storage") # Путь монтирования в Docker
SEARCH_ENGINE_URL: str = os.getenv("MEILI_URL", "http://meilisearch:7700")
MEILI_API_KEY: Optional[str] = os.getenv("MEILI_MASTER_KEY") # Используйте Master Key или Search API Key
INDEX_NAME: str = "documents"

app = FastAPI(
    title="Document Search API",
    description="API для поиска по локальным документам и их получения",
    version="0.2.0",
)

# Зависимость для получения HTTP-клиента (лучше использовать один клиент)
# В реальном приложении можно использовать httpx.AsyncClient
# Для простоты пока оставляем requests
def get_search_session() -> requests.Session:
    """Создает сессию requests с заголовками для Meilisearch."""
    session = requests.Session()
    headers = {}
    if MEILI_API_KEY:
        headers["Authorization"] = f"Bearer {MEILI_API_KEY}"
    session.headers.update(headers)
    return session

@app.get("/search", response_model=Dict[str, List[Dict[str, Any]]], summary="Поиск документов")
async def search(
    q: str = Query(..., description="Поисковый запрос"),
    limit: int = Query(20, ge=1, le=100, description="Максимальное количество результатов"),
    session: requests.Session = Depends(get_search_session)
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Выполняет поиск документов в индексе Meilisearch.
    """
    search_url = f"{SEARCH_ENGINE_URL}/indexes/{INDEX_NAME}/search"
    params = {"q": q, "limit": limit, "attributesToHighlight": ["content"]} # Запрашиваем подсветку
    try:
        response = session.post(search_url, json=params) # Meilisearch рекомендует POST для поиска с параметрами
        response.raise_for_status() # Вызовет исключение для кодов 4xx/5xx
        results = response.json()
        logger.info(f"Поиск по запросу '{q}' вернул {len(results.get('hits', []))} результатов")
        # Возвращаем только нужные поля, включая _formatted для подсветки
        hits = []
        for hit in results.get("hits", []):
             # Убираем полный content, если он большой, оставляем только id и _formatted
            formatted_hit = hit.get("_formatted", {"id": hit.get("id", "N/A"), "content": "..."})
            formatted_hit["id"] = hit.get("id", "N/A") # Убедимся, что id всегда есть
            hits.append(formatted_hit)

        return {"results": hits}

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при обращении к Meilisearch ({search_url}): {e}")
        raise HTTPException(status_code=503, detail="Сервис поиска временно недоступен")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске: {e}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера при поиске")


@app.get("/files/{filename}", summary="Получение файла документа")
async def get_file(filename: str) -> FileResponse:
    """
    Возвращает файл по его имени.
    Используется для скачивания файлов, найденных через поиск.
    """
    if not filename or ".." in filename or "/" in filename:
        logger.warning(f"Попытка доступа к некорректному имени файла: {filename}")
        raise HTTPException(status_code=400, detail="Некорректное имя файла")

    file_path = os.path.join(FILES_DIR, filename)
    # Проверка безопасности: убеждаемся, что путь действительно внутри FILES_DIR
    if not os.path.abspath(file_path).startswith(os.path.abspath(FILES_DIR)):
         logger.error(f"Попытка доступа за пределы разрешенной директории: {file_path}")
         raise HTTPException(status_code=403, detail="Доступ запрещен")

    if os.path.exists(file_path) and os.path.isfile(file_path):
        logger.info(f"Отдаем файл: {filename}")
        # media_type можно определять более точно, если нужно
        return FileResponse(file_path, filename=filename)
    else:
        logger.warning(f"Запрошенный файл не найден: {filename} (путь {file_path})")
        raise HTTPException(status_code=404, detail="Файл не найден")

# Можно добавить эндпоинт для статуса системы, проверки подключения к MeiliSearch и т.д.
@app.get("/health", summary="Проверка состояния сервиса")
async def health_check(session: requests.Session = Depends(get_search_session)) -> Dict[str, str]:
    """Проверяет доступность бэкенда и Meilisearch."""
    meili_status = "недоступен"
    try:
        health_url = f"{SEARCH_ENGINE_URL}/health"
        response = session.get(health_url)
        response.raise_for_status()
        if response.json().get("status") == "available":
             meili_status = "доступен"
    except requests.exceptions.RequestException:
        pass # Статус останется "недоступен"
    except Exception as e:
         logger.error(f"Неожиданная ошибка при проверке здоровья Meilisearch: {e}")


    return {"status": "ok", "meilisearch_status": meili_status}


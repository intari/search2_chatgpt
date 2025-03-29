from fastapi import FastAPI
from fastapi.responses import FileResponse
import requests
import os
from dotenv import load_dotenv

load_dotenv()
FILES_DIR = os.getenv("LOCAL_STORAGE_PATH", "/mnt/storage")
SEARCH_ENGINE = "http://meilisearch:7700"

app = FastAPI()

@app.get("/search")
def search(q: str):
    response = requests.get(f"{SEARCH_ENGINE}/indexes/documents/search", params={"q": q})
    results = response.json()
    return {"results": results.get("hits", [])}

@app.get("/files/{filename}")
def get_file(filename: str):
    file_path = os.path.join(FILES_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    return {"error": "Файл не найден"}

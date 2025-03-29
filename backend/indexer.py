import os
import requests
from pdfminer.high_level import extract_text
from ebooklib import epub
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
FILES_DIR = os.getenv("LOCAL_STORAGE_PATH", "/mnt/storage")
SEARCH_ENGINE = "http://meilisearch:7700"
INDEX_NAME = "documents"

def extract_text_from_pdf(pdf_path):
    return extract_text(pdf_path)

def extract_text_from_epub(epub_path):
    book = epub.read_epub(epub_path)
    text = []
    for item in book.get_items():
        if item.get_type() == 9:
            soup = BeautifulSoup(item.content, "html.parser")
            text.append(soup.get_text())
    return "\n".join(text)

def index_files():
    docs = []
    for filename in os.listdir(FILES_DIR):
        file_path = os.path.join(FILES_DIR, filename)

        if filename.endswith(".txt"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        elif filename.endswith(".pdf"):
            content = extract_text_from_pdf(file_path)
        elif filename.endswith(".epub"):
            content = extract_text_from_epub(file_path)
        else:
            continue

        docs.append({"id": filename, "content": content})

    if docs:
        requests.post(f"{SEARCH_ENGINE}/indexes/{INDEX_NAME}/documents", json=docs)
        print(f"Индексировано {len(docs)} файлов!")

if __name__ == "__main__":
    index_files()

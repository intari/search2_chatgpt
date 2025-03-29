import os
import chardet

DIRECTORY = "./"  # Замени на путь к папке с файлами

def detect_encoding(filename):
    with open(filename, "rb") as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result["encoding"]

def check_all_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            filepath = os.path.join(root, file)
            encoding = detect_encoding(filepath)
            if encoding and "utf-16" in encoding.lower():
                print(f"❌ {filepath} - {encoding}")

print("🔍 Поиск файлов с UTF-16...")
check_all_files(DIRECTORY)
print("✅ Готово!")
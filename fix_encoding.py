import os
import chardet
import codecs

DIRECTORY = "./local_files"  # Путь к папке с файлами

def convert_to_utf8(filename):
    with open(filename, "rb") as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result["encoding"]
    
    if encoding and "utf-16" in encoding.lower():
        print(f"🔄 Конвертирую {filename} ({encoding}) в UTF-8...")
        with codecs.open(filename, "r", encoding=encoding) as f:
            content = f.read()
        with codecs.open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ {filename} теперь в UTF-8!")

def fix_all_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            filepath = os.path.join(root, file)
            convert_to_utf8(filepath)

print("🔍 Исправление кодировки...")
fix_all_files(DIRECTORY)
print("✅ Готово!")

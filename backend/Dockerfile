# backend/Dockerfile

FROM python:3.11

WORKDIR /app

# Копируем сначала requirements, чтобы кэшировать слой установки зависимостей
COPY requirements.txt .
# Устанавливаем зависимости приложения и тестов
# Используем --no-cache-dir для уменьшения размера образа
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения и тесты
COPY . .

# Команда по умолчанию для запуска приложения
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

# Пример команды для запуска тестов (можно использовать при CI/CD или вручную)
# RUN pytest

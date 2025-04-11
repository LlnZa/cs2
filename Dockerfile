# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочий каталог внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями и устанавливаем их
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё остальное из текущего каталога в рабочий каталог контейнера
COPY . .

# Указываем порт, на котором будет работать приложение (например, 5000)
EXPOSE 5000

# Команда для запуска приложения
CMD ["python", "server.py"]

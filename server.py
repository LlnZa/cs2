from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
import os

# Настройки подключения к БД
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    else:
        # Локальные настройки для разработки
        conn = psycopg2.connect(
            dbname="cs2_esports",
            user="postgres",
            password="postgres",
            host="localhost",
            port="5432",
            cursor_factory=RealDictCursor
        )
    return conn

def get_live_matches():
    """
    Выбирает из таблицы matches только live-матчи (например, где status = 'running').
    При необходимости можно расширить условие.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM matches WHERE status = 'running';"
    cur.execute(query)
    matches = cur.fetchall()
    cur.close()
    conn.close()
    return matches

# Создаём экземпляр FastAPI
app = FastAPI()

# Подключаем статические файлы (например, для CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Подключаем шаблоны из папки templates
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    """
    Главный маршрут: получает live-матчи из базы и передаёт их в шаблон index.html.
    """
    matches = get_live_matches()
    return templates.TemplateResponse("index.html", {"request": request, "matches": matches})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

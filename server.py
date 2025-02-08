import os
import json
import requests
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.background import BackgroundScheduler

# =======================
# 1. Настройки подключения к БД
# =======================
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

# =======================
# 2. Функции для работы с API
# =======================
API_TOKEN = os.getenv("API_TOKEN", "o9lfBugxpaB8acOZJusXrSUDtFGCfqtXiMe0nTOkC3LagsGDjRA")  # Задайте токен, либо через env
API_BASE_URL = "https://api.pandascore.co/csgo"

def fetch_api(endpoint):
    """Получает данные с API по заданному endpoint."""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка запроса к API {endpoint}: {e}")
        return None

def parse_datetime(dt_str):
    """Преобразует строку ISO в объект datetime; возвращает None, если dt_str равно None."""
    if dt_str is None:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception as e:
        print(f"Ошибка преобразования даты {dt_str}: {e}")
        return None

# =======================
# 3. Функции вставки данных в таблицы
# =======================

def insert_team(team):
    """Вставляет данные о команде в таблицу teams."""
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        INSERT INTO teams (team_id, name, acronym, location, image_url)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (team_id) DO NOTHING;
    """
    data = (
        team.get("id"),
        team.get("name"),
        team.get("acronym"),
        team.get("location"),
        team.get("image_url")
    )
    try:
        cur.execute(query, data)
        conn.commit()
    except Exception as e:
        print(f"Ошибка вставки команды {team.get('id')}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def insert_league(league):
    """Вставляет данные о лиге в таблицу leagues."""
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        INSERT INTO leagues (league_id, name, slug)
        VALUES (%s, %s, %s)
        ON CONFLICT (league_id) DO NOTHING;
    """
    data = (
        league.get("id"),
        league.get("name"),
        league.get("slug")
    )
    try:
        cur.execute(query, data)
        conn.commit()
    except Exception as e:
        print(f"Ошибка вставки лиги {league.get('id')}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def insert_series(series):
    """Вставляет данные о серии (турнирной серии) в таблицу series."""
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        INSERT INTO series (serie_id, name, full_name, year, begin_at, end_at, league_id, league_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (serie_id) DO NOTHING;
    """
    full_name = series.get("full_name") or series.get("name")
    begin_at = parse_datetime(series.get("begin_at"))
    end_at = parse_datetime(series.get("end_at"))
    data = (
        series.get("id"),
        series.get("name"),
        full_name,
        series.get("year"),
        begin_at,
        end_at,
        series.get("league_id"),
        series.get("league", {}).get("name")
    )
    try:
        cur.execute(query, data)
        conn.commit()
    except Exception as e:
        print(f"Ошибка вставки серии {series.get('id')}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def insert_match(match):
    """
    Вставляет данные о матче в таблицу matches.
    Поле videogame_title исключено, так как все матчи по одной игре.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        INSERT INTO matches 
        (match_id, name, status, scheduled_at, original_scheduled_at, begin_at, modified_at,
         match_type, forfeit, rescheduled, number_of_games, tournament_id, serie_id, league_id, 
         live_supported, live_url, live_opens_at, streams_list,
         final_score_team1, final_score_team2, live_score_team1, live_score_team2,
         team1_id, team2_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id) DO NOTHING;
    """
    scheduled_at = parse_datetime(match.get("scheduled_at"))
    original_scheduled_at = parse_datetime(match.get("original_scheduled_at"))
    begin_at = parse_datetime(match.get("begin_at"))
    modified_at = parse_datetime(match.get("modified_at"))
    live = match.get("live", {})
    live_supported = live.get("supported")
    live_url = live.get("url")
    live_opens_at = parse_datetime(live.get("opens_at"))
    streams_list = json.dumps(match.get("streams_list", []))
    # Если присутствует поле results, берем финальный счет (предполагается, что их два)
    results = match.get("results")
    if results and isinstance(results, list) and len(results) >= 2:
        final_score_team1 = results[0].get("score")
        final_score_team2 = results[1].get("score")
    else:
        final_score_team1 = None
        final_score_team2 = None
    # Live-счёт (если есть)
    live_score_team1 = None
    live_score_team2 = None

    # Из opponents – получаем id команд
    opponents = match.get("opponents", [])
    team1_id = opponents[0]["opponent"].get("id") if len(opponents) > 0 else None
    team2_id = opponents[1]["opponent"].get("id") if len(opponents) > 1 else None

    serie_obj = match.get("serie")
    serie_id = serie_obj.get("id") if serie_obj else None

    data = (
        match.get("id"),
        match.get("name"),
        match.get("status"),
        scheduled_at,
        original_scheduled_at,
        begin_at,
        modified_at,
        match.get("match_type"),
        match.get("forfeit"),
        match.get("rescheduled"),
        match.get("number_of_games"),
        match.get("tournament_id"),
        serie_id,
        match.get("league_id"),
        live_supported,
        live_url,
        live_opens_at,
        streams_list,
        final_score_team1,
        final_score_team2,
        live_score_team1,
        live_score_team2,
        team1_id,
        team2_id
    )
    try:
        cur.execute(query, data)
        conn.commit()
    except Exception as e:
        print(f"Ошибка вставки матча {match.get('id')}: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# =======================
# 4. Функция обновления live-матчей из API
# =======================
def process_live_matches():
    print("Получение live-матчей из API...")
    live_matches = fetch_api("/matches/running")
    if live_matches is None:
        print("Нет данных по live-матчам.")
        return
    for match in live_matches:
        # Обработка команд
        opponents = match.get("opponents", [])
        for opp in opponents:
            team = opp.get("opponent")
            if team:
                insert_team(team)
        # Обработка лиги (если есть)
        league = match.get("league")
        if league:
            insert_league(league)
        # Обработка серии (если есть)
        serie = match.get("serie")
        if serie:
            insert_series(serie)
        # Вставляем данные о матче
        insert_match(match)
        print(f"Матч {match.get('id')} ({match.get('name')}) обработан.")

# =======================
# 5. Планировщик APScheduler
# =======================
scheduler = BackgroundScheduler()

# Функция, которая будет запускаться каждые 15 минут
scheduler.add_job(process_live_matches, 'interval', minutes=15)

# При запуске приложения запускаем планировщик
@app.on_event("startup")
def startup_event():
    print("Запуск планировщика обновления live-матчей...")
    scheduler.start()
    # Можно сразу вызвать обновление, если нужно:
    process_live_matches()

# Останавливаем планировщик при завершении работы приложения
@app.on_event("shutdown")
def shutdown_event():
    print("Остановка планировщика...")
    scheduler.shutdown()

# =======================
# 6. FastAPI приложение
# =======================
app = FastAPI()

# Подключаем статические файлы
app.mount("/static", StaticFiles(directory="static"), name="static")
# Подключаем шаблоны
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    """
    Главный маршрут: получает live-матчи из базы и передаёт их в шаблон index.html.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM matches WHERE status = 'running';"
    cur.execute(query)
    matches = cur.fetchall()
    cur.close()
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "matches": matches})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

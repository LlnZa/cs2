import os
import re
import json
import requests
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.background import BackgroundScheduler

# =======================
# 1. Настройки подключения к базе данных
# =======================
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Используем URL из переменной окружения (например, Render External Database URL)
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

def execute_query(query, params):
    """Вспомогательная функция для выполнения запроса с параметрами."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        conn.commit()
    except Exception as e:
        print(f"Ошибка выполнения запроса: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# =======================
# 2. Настройки API
# =======================
API_TOKEN = os.getenv("API_TOKEN", "o9lfBugxpaB8acOZJusXrSUDtFGCfqtXiMe0nTOkC3LagsGDjRA")
API_BASE_URL = "https://api.pandascore.co/csgo"

def fetch_api(endpoint):
    """Получает данные с API по заданному endpoint."""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {API_TOKEN}"
    }
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
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        INSERT INTO matches 
        (match_id, name, status, scheduled_at, original_scheduled_at, number_of_games, tournament_id, serie_id, league_id, 
         live_supported, live_url, live_opens_at, streams_list,
         final_score_team1, final_score_team2, team1_id, team2_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id) DO UPDATE 
         SET final_score_team1 = EXCLUDED.final_score_team1,
             final_score_team2 = EXCLUDED.final_score_team2,
             status = EXCLUDED.status;
    """
    scheduled_at = parse_datetime(match.get("scheduled_at"))
    original_scheduled_at = parse_datetime(match.get("original_scheduled_at"))
    results = match.get("results")
    if results and isinstance(results, list) and len(results) >= 2:
        final_score_team1 = results[0].get("score")
        final_score_team2 = results[1].get("score")
    else:
        final_score_team1 = None
        final_score_team2 = None
    opponents = match.get("opponents", [])
    team1_id = opponents[0]["opponent"].get("id") if len(opponents) > 0 else None
    team2_id = opponents[1]["opponent"].get("id") if len(opponents) > 1 else None
    serie_obj = match.get("serie")
    serie_id = serie_obj.get("id") if serie_obj else None
    live = match.get("live", {})
    live_supported = live.get("supported")
    data = (
        match.get("id"),
        f"{opponents[0]['opponent'].get('name','-')} vs {opponents[1]['opponent'].get('name','-')}",
        match.get("status"),
        scheduled_at,
        original_scheduled_at,
        match.get("number_of_games"),
        match.get("tournament_id"),
        serie_id,
        match.get("league_id"),
        live_supported,
        live.get("url"),
        parse_datetime(live.get("opens_at")),
        json.dumps(match.get("streams_list", [])),
        final_score_team1,
        final_score_team2,
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
# 4a. Обновление past-матчей (для завершённых матчей)
def process_past_matches():
    print("Получение past-матчей из API...")
    past_matches = fetch_api("/matches/past")
    if past_matches is None:
        print("Нет данных по past-матчам.")
        return
    for match in past_matches:
        for opp in match.get("opponents", []):
            team = opp.get("opponent")
            if team:
                insert_team(team)
        league = match.get("league")
        if league:
            insert_league(league)
        serie = match.get("serie")
        if serie:
            insert_series(serie)
        insert_match(match)
        print(f"Past-матч {match.get('id')} ({match.get('name')}) обработан.")

# =======================
# 4b. Обновление live-матчей
def process_live_matches():
    print("Получение live-матчей из API...")
    live_matches = fetch_api("/matches/running")
    if live_matches is None:
        print("Нет данных по live-матчам.")
        return
    for match in live_matches:
        for opp in match.get("opponents", []):
            team = opp.get("opponent")
            if team:
                insert_team(team)
        league = match.get("league")
        if league:
            insert_league(league)
        serie = match.get("serie")
        if serie:
            insert_series(serie)
        insert_match(match)
        print(f"Live-матч {match.get('id')} ({match.get('name')}) обработан.")

def process_all_matches():
    process_live_matches()
    process_past_matches()

# =======================
# 5. Функция загрузки рейтингов с GitHub и сохранения в таблицу ratings
# =======================
def save_ratings():
    print("🔄 Загружаем рейтинги с GitHub...")
    rating_api_url = "https://api.github.com/repos/ValveSoftware/counter-strike_regional_standings/contents/live/2025"
    # Добавляем заголовки, необходимые GitHub API
    headers = {
        "User-Agent": "cs2-rating-fetcher",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(rating_api_url, headers=headers)
    if response.status_code != 200:
        print(f"❌ Ошибка получения списка рейтингов: {response.status_code}")
        return
    files = response.json()
    rating_files = [f for f in files if re.match(r"standings_global_\d{4}_\d{2}_\d{2}\.md", f.get("name", ""))]
    if not rating_files:
        print("❌ Файлы рейтингов не найдены.")
        return
    rating_files.sort(key=lambda f: datetime.strptime(re.search(r"\d{4}_\d{2}_\d{2}", f["name"]).group(), "%Y_%m_%d"), reverse=True)
    latest_file = rating_files[0]
    download_url = latest_file.get("download_url")
    if not download_url:
        print("❌ Нет ссылки для скачивания рейтинга.")
        return
    rating_response = requests.get(download_url, headers=headers)
    if rating_response.status_code != 200:
        print(f"❌ Ошибка скачивания рейтингов: {rating_response.status_code}")
        return
    content = rating_response.text
    lines = content.splitlines()
    if len(lines) < 3:
        print("❌ Недостаточно данных в рейтинговом файле.")
        return
    ratings_data = []
    # Пропускаем заголовок и разделительную строку
    for line in lines[2:]:
        if not line.strip() or not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 3:
            continue
        try:
            standing = int(parts[0])
            points = int(parts[1])
        except Exception:
            continue
        team_name = parts[2]
        roster = parts[3] if len(parts) > 3 else ""
        ratings_data.append((team_name, standing, points, roster))
    for team_name, standing, points, roster in ratings_data:
        query = """
            INSERT INTO ratings (team_name, rank, points, roster, last_updated)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (team_name) DO UPDATE
            SET rank = EXCLUDED.rank,
                points = EXCLUDED.points,
                roster = EXCLUDED.roster,
                last_updated = NOW();
        """
        execute_query(query, (team_name, standing, points, roster))
    print("✅ Рейтинги сохранены.")

# =======================
# 6. Генерация списка дат (за последние 10 дней)
def generate_date_list():
    today = datetime.today().date()
    date_list = []
    days_map = {
        'Monday': 'Пн',
        'Tuesday': 'Вт',
        'Wednesday': 'Ср',
        'Thursday': 'Чт',
        'Friday': 'Пт',
        'Saturday': 'Сб',
        'Sunday': 'Вс'
    }
    for i in range(10):
        d = today - timedelta(days=i)
        short_name = days_map.get(d.strftime("%A"), d.strftime("%a"))
        date_list.append({
            "full_date": d.strftime("%Y-%m-%d"),
            "day": d.day,
            "month": d.strftime("%m"),
            "short_name": short_name
        })
    date_list.sort(key=lambda x: x["full_date"], reverse=True)
    return date_list

# =======================
# 7. Получение матчей для отображения (группировка по дате)
def get_display_matches_grouped(selected_date: str = None):
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        SELECT 
            m.match_id,
            CASE 
                WHEN m.number_of_games = 1 THEN 'bo1'
                WHEN m.number_of_games = 3 THEN 'bo3'
                WHEN m.number_of_games = 5 THEN 'bo5'
                ELSE 'bo' || m.number_of_games
            END AS bo_format,
            CASE 
                WHEN LOWER(m.status) = 'running' THEN to_char(current_date, 'YYYY-MM-DD')
                ELSE to_char(m.scheduled_at, 'YYYY-MM-DD')
            END AS match_date,
            to_char(m.scheduled_at, 'HH24:MI') AS match_time,
            s.full_name AS series_full_name,
            t1.name AS team1_name,
            t1.image_url AS team1_logo,
            t2.name AS team2_name,
            t2.image_url AS team2_logo,
            m.final_score_team1,
            m.final_score_team2,
            CASE 
                WHEN LOWER(m.status) = 'running' THEN 'Live'
                WHEN LOWER(m.status) = 'finished' THEN 'Завершён'
                ELSE m.status
            END AS display_status
        FROM matches m
        LEFT JOIN series s ON m.serie_id = s.serie_id
        LEFT JOIN teams t1 ON m.team1_id = t1.team_id
        LEFT JOIN teams t2 ON m.team2_id = t2.team_id
        WHERE m.scheduled_at >= CURRENT_DATE - INTERVAL '10 days'
    """
    params = []
    if not selected_date:
        selected_date = datetime.today().strftime("%Y-%m-%d")
    query += " AND (CASE WHEN LOWER(m.status) = 'running' THEN to_char(current_date, 'YYYY-MM-DD') ELSE to_char(m.scheduled_at, 'YYYY-MM-DD') END) = %s"
    params.append(selected_date)
    query += """
        ORDER BY 
            CASE WHEN LOWER(m.status) = 'running' THEN 0 ELSE 1 END,
            m.scheduled_at DESC;
    """
    cur.execute(query, tuple(params))
    matches = cur.fetchall()
    cur.close()
    conn.close()

    grouped = {}
    for m in matches:
        date = m.get("match_date")
        if date not in grouped:
            grouped[date] = []
        grouped[date].append(m)
    sorted_grouped = dict(sorted(grouped.items(), reverse=True))
    return sorted_grouped

# =======================
# 8. Планировщик обновления (каждые 1 минут для матчей, каждые 15 минут для рейтингов)
scheduler = BackgroundScheduler()
scheduler.add_job(process_all_matches, 'interval', minutes=1)
scheduler.add_job(save_ratings, 'interval', minutes=15)

def process_all_matches():
    process_live_matches()
    process_past_matches()

# =======================
# 9. Создание FastAPI приложения, подключение статики и шаблонов
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def startup_event():
    print("Запуск планировщика обновления матчей и рейтингов...")
    scheduler.start()
    process_all_matches()
    save_ratings()

@app.on_event("shutdown")
def shutdown_event():
    print("Остановка планировщика...")
    scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, date: str = None):
    grouped_matches = get_display_matches_grouped(selected_date=date)
    date_list = generate_date_list()
    if not date:
        date = datetime.today().strftime("%Y-%m-%d")
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "grouped_matches": grouped_matches, 
        "date_list": date_list,
        "selected_date": date
    })

@app.get("/rating", response_class=HTMLResponse)
def rating_page(request: Request):
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        SELECT 
            r.team_name,
            r.rank,
            r.points,
            r.roster,
            t.image_url AS team_logo
        FROM ratings r
        LEFT JOIN teams t ON r.team_name = t.name
        ORDER BY r.points DESC;
    """
    cur.execute(query)
    ratings = cur.fetchall()
    cur.close()
    conn.close()
    return templates.TemplateResponse("rating.html", {"request": request, "ratings": ratings})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>CS2 Esports WebApp</title>
</head>
<body>
    <h1>Список ближайших матчей</h1>
    <ul>
        <li>G2 vs NAVI - 10:00 12.02.2025</li>
        <li>FaZe vs Vitality - 14:00 12.02.2025</li>
        <li>ENCE vs Heroic - 18:00 12.02.2025</li>
    </ul>
</body>
</html>
"""

@app.get("/")
async def read_root():
    return HTMLResponse(content=HTML_CONTENT, status_code=200)

if __name__ == "__main__":
    import os
port = int(os.getenv("PORT", 8000))
uvicorn.run(app, host="0.0.0.0", port=port)


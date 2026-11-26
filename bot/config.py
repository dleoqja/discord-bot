"""환경 변수 로딩 및 설정값 관리."""
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Riot Games API 키 (롤 전적 조회용) — https://developer.riotgames.com
RIOT_API_KEY = os.getenv("RIOT_API_KEY")

# Groq API 키 (/ai 대화용, 무료) — https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# 선택: 먼저 쓸 모델 이름 (비우면 기본 순서 사용)
GROQ_MODEL = os.getenv("GROQ_MODEL", "").strip()

# GUILD_ID가 있으면 해당 서버에만 즉시 슬래시 명령어 동기화 (개발 중 편리)
_guild_id = os.getenv("GUILD_ID", "").strip()
GUILD_ID = int(_guild_id) if _guild_id.isdigit() else None

# SQLite 데이터베이스 경로
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.sqlite3")

# 로드할 Cog(기능 모듈) 목록
INITIAL_COGS = [
    "bot.cogs.lol",
    "bot.cogs.mhxx",
    "bot.cogs.assistant",
    "bot.cogs.recruit",
]

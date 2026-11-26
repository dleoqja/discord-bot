"""SQLite 기반 간단 데이터 계층 (유저 포인트 저장/조회)."""
import sqlite3
from contextlib import closing

from bot.config import DB_PATH


def init_db() -> None:
    """앱 시작 시 테이블을 생성한다 (없을 때만)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                points  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # 디스코드 계정 <-> 롤 계정 연결 (+ 자동 분석 설정)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS linked_accounts (
                discord_id      INTEGER PRIMARY KEY,
                game_name       TEXT NOT NULL,
                tag_line        TEXT NOT NULL,
                puuid           TEXT NOT NULL,
                platform        TEXT NOT NULL,
                auto_channel_id INTEGER,
                last_match_id   TEXT
            )
            """
        )
        # 이전 버전 DB 마이그레이션: 자동 인게임 알림용 컬럼 추가
        cols = {r[1] for r in conn.execute("PRAGMA table_info(linked_accounts)")}
        if "last_live_game_id" not in cols:
            conn.execute("ALTER TABLE linked_accounts ADD COLUMN last_live_game_id TEXT")
        conn.commit()


# ── 롤 계정 링크 / 자동 분석 ──

def link_account(
    discord_id: int, game_name: str, tag_line: str, puuid: str, platform: str
) -> None:
    """디스코드 계정에 롤 계정을 연결(또는 갱신)한다. 자동분석 설정은 유지."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO linked_accounts (discord_id, game_name, tag_line, puuid, platform)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                game_name = excluded.game_name,
                tag_line  = excluded.tag_line,
                puuid     = excluded.puuid,
                platform  = excluded.platform
            """,
            (discord_id, game_name, tag_line, puuid, platform),
        )
        conn.commit()


def get_linked(discord_id: int) -> dict | None:
    """연결된 롤 계정 정보를 dict로 반환. 없으면 None."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM linked_accounts WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return dict(row) if row else None


def set_auto_channel(discord_id: int, channel_id: int | None) -> None:
    """자동 분석을 게시할 채널을 설정(또는 해제)한다."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "UPDATE linked_accounts SET auto_channel_id = ? WHERE discord_id = ?",
            (channel_id, discord_id),
        )
        conn.commit()


def update_last_match(discord_id: int, match_id: str) -> None:
    """마지막으로 분석한 매치 ID를 저장한다 (중복 게시 방지용)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "UPDATE linked_accounts SET last_match_id = ? WHERE discord_id = ?",
            (match_id, discord_id),
        )
        conn.commit()


def update_last_live_game(discord_id: int, game_id: str) -> None:
    """마지막으로 알린 진행 중 게임 ID를 저장한다 (인게임 알림 중복 방지용)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "UPDATE linked_accounts SET last_live_game_id = ? WHERE discord_id = ?",
            (game_id, discord_id),
        )
        conn.commit()


def all_auto_accounts() -> list[dict]:
    """자동 분석이 켜진 모든 계정 목록을 반환한다."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM linked_accounts WHERE auto_channel_id IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def add_points(user_id: int, amount: int) -> int:
    """유저 포인트를 증감시키고, 갱신된 총 포인트를 반환한다."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, points) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET points = points + ?
            """,
            (user_id, amount, amount),
        )
        conn.commit()
        row = conn.execute(
            "SELECT points FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else 0


def get_points(user_id: int) -> int:
    """유저의 현재 포인트를 반환한다."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT points FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else 0


def top_users(limit: int = 5) -> list[tuple[int, int]]:
    """포인트 상위 유저 목록 [(user_id, points), ...] 을 반환한다."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            "SELECT user_id, points FROM users ORDER BY points DESC LIMIT ?",
            (limit,),
        ).fetchall()

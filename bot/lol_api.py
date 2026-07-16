"""Riot Games API 클라이언트 (롤 전적 조회).

라우팅 개념:
- platform (kr, na1, euw1 ...): 소환사/랭크 정보용
- region   (asia, americas, europe): 계정(PUUID)/매치 정보용
"""
import asyncio
import ssl

import aiohttp
import certifi

from bot import config

# 429(레이트 리밋) 자동 재시도 설정
MAX_RETRIES = 3
MAX_RETRY_WAIT = 10  # Retry-After가 이보다 크면 그냥 에러 처리 (초)


def ssl_context() -> ssl.SSLContext:
    """certifi 인증서 번들 기반 SSL 컨텍스트 (Windows 인증서 검증 오류 방지)."""
    return ssl.create_default_context(cafile=certifi.where())

# platform(플랫폼) -> region(대륙) 매핑
PLATFORM_TO_REGION = {
    "kr": "asia", "jp1": "asia",
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
}


class RiotAPIError(Exception):
    """API 호출 실패를 사용자 메시지와 함께 전달."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def _get(session: aiohttp.ClientSession, url: str) -> dict:
    """공통 GET 요청. 상태 코드별로 사람이 읽을 수 있는 에러로 변환.

    429(레이트 리밋)는 Retry-After 헤더만큼 기다렸다 자동 재시도한다.
    """
    headers = {"X-Riot-Token": config.RIOT_API_KEY or ""}
    for attempt in range(MAX_RETRIES):
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            if resp.status == 401 or resp.status == 403:
                raise RiotAPIError(
                    "API 키가 없거나 만료됐어요. (개발용 키는 24시간마다 만료돼요)"
                )
            if resp.status == 404:
                raise RiotAPIError(
                    "소환사를 찾을 수 없어요. 이름/태그/지역을 확인해주세요."
                )
            if resp.status == 429:
                wait = int(resp.headers.get("Retry-After", "2"))
                # 마지막 시도이거나 대기가 너무 길면 포기
                if attempt == MAX_RETRIES - 1 or wait > MAX_RETRY_WAIT:
                    raise RiotAPIError(
                        "요청이 너무 많아요. 잠시 후 다시 시도해주세요."
                    )
                await asyncio.sleep(wait)
                continue
            raise RiotAPIError(f"Riot API 오류 (HTTP {resp.status})")
    raise RiotAPIError("요청이 너무 많아요. 잠시 후 다시 시도해주세요.")


async def get_account(
    session: aiohttp.ClientSession, region: str, game_name: str, tag_line: str
) -> dict:
    """라이엇 ID(이름#태그)로 계정 정보(puuid 포함)를 조회한다."""
    url = (
        f"https://{region}.api.riotgames.com/riot/account/v1/accounts/"
        f"by-riot-id/{game_name}/{tag_line}"
    )
    return await _get(session, url)


async def get_summoner(
    session: aiohttp.ClientSession, platform: str, puuid: str
) -> dict:
    """puuid로 소환사 정보(레벨 등)를 조회한다."""
    url = (
        f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/"
        f"by-puuid/{puuid}"
    )
    return await _get(session, url)


async def get_ranked(
    session: aiohttp.ClientSession, platform: str, puuid: str
) -> list[dict]:
    """puuid로 랭크(솔로/자유) 정보를 조회한다."""
    url = (
        f"https://{platform}.api.riotgames.com/lol/league/v4/entries/"
        f"by-puuid/{puuid}"
    )
    return await _get(session, url)


async def get_mastery(
    session: aiohttp.ClientSession, platform: str, puuid: str
) -> list[dict]:
    """puuid로 챔피언 숙련도 목록(숙련도 높은 순)을 조회한다."""
    url = (
        f"https://{platform}.api.riotgames.com/lol/champion-mastery/v4/"
        f"champion-masteries/by-puuid/{puuid}"
    )
    return await _get(session, url)


async def get_match_ids(
    session: aiohttp.ClientSession, region: str, puuid: str, count: int = 5
) -> list[str]:
    """최근 매치 ID 목록을 조회한다."""
    url = (
        f"https://{region}.api.riotgames.com/lol/match/v5/matches/"
        f"by-puuid/{puuid}/ids?count={count}"
    )
    return await _get(session, url)


async def get_match(
    session: aiohttp.ClientSession, region: str, match_id: str
) -> dict:
    """매치 상세 정보를 조회한다."""
    url = (
        f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    )
    return await _get(session, url)

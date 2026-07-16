"""Data Dragon 헬퍼: 챔피언 한글 이름 매핑 + 챔피언 얼굴 이미지 다운로드/캐싱.

Data Dragon은 Riot의 공개 정적 데이터 CDN이라 API 키가 필요 없다.
"""
import os

import aiohttp

ASSET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "assets", "champions"
)

_version: str | None = None
# 숫자 championId(str) -> {"id": "Ahri", "name": "아리"}
_champ_by_key: dict[str, dict] | None = None


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> dict | list:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.json()


async def get_version(session: aiohttp.ClientSession) -> str:
    """최신 Data Dragon 버전을 가져온다 (프로세스 내 캐싱)."""
    global _version
    if _version is None:
        data = await _fetch_json(
            session, "https://ddragon.leagueoflegends.com/api/versions.json"
        )
        _version = data[0]
    return _version


async def load_champion_map(session: aiohttp.ClientSession) -> dict[str, dict]:
    """championId(숫자) -> {id, name(한글)} 매핑을 로드한다 (캐싱)."""
    global _champ_by_key
    if _champ_by_key is None:
        ver = await get_version(session)
        url = (
            f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/ko_KR/champion.json"
        )
        data = await _fetch_json(session, url)
        _champ_by_key = {
            info["key"]: {"id": info["id"], "name": info["name"]}
            for info in data["data"].values()
        }
    return _champ_by_key


def image_url(ddragon_id: str | None) -> str | None:
    """챔피언 얼굴 이미지의 공개 CDN URL (임베드 썸네일용). 버전 로드 후 사용."""
    if not ddragon_id or _version is None:
        return None
    return (
        f"https://ddragon.leagueoflegends.com/cdn/{_version}/img/champion/{ddragon_id}.png"
    )


def champ_info(champion_id: int) -> dict:
    """숫자 championId로 {id, name}을 반환. 없으면 물음표 처리."""
    if _champ_by_key is None:
        return {"id": None, "name": "?"}
    return _champ_by_key.get(str(champion_id), {"id": None, "name": "?"})


async def get_champion_image(
    session: aiohttp.ClientSession, ddragon_id: str | None
) -> str | None:
    """챔피언 얼굴 이미지를 다운로드해 로컬 경로를 반환. 캐시되어 있으면 재사용."""
    if not ddragon_id:
        return None
    os.makedirs(ASSET_DIR, exist_ok=True)
    path = os.path.join(ASSET_DIR, f"{ddragon_id}.png")
    if os.path.exists(path):
        return path

    ver = await get_version(session)
    url = (
        f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/champion/{ddragon_id}.png"
    )
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.read()
    with open(path, "wb") as f:
        f.write(data)
    return path

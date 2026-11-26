"""롤 전적 조회 Cog.

명령어:
- /lol       이름#태그로 전적 카드 조회
- /링크       내 디스코드에 롤 계정 연결
- /내전적     연결된 내 계정 전적 바로 조회
- /자동분석   이 채널에 게임 시작 시 인게임 정보 + 게임 종료 시 AI 한마디 분석 자동 게시 (on/off)
- /인게임     진행 중인 게임의 참가자 10명 티어/승률 (이름 생략 시 연결된 내 계정)

백그라운드: 3분마다 자동분석 켠 유저를 확인해
  - 새 게임이 시작됐으면 인게임 정보를,
  - 새 게임이 끝났으면 분석(+AI 한마디)을 올린다.
"""
import asyncio
import io
import logging
import time
from collections import defaultdict, deque
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot import ai, config, database, ddragon, image_card, lol_api

log = logging.getLogger("bot.lol")

RECENT_COUNT = 10   # 최근 전적 표시 개수
STATS_COUNT = 15    # 모스트/승률/라인 계산에 쓸 최근 게임 수
CONCURRENCY = 5     # 매치 상세 동시 요청 수 (레이트 리밋 완화)

# 라인(포지션) 한글 표기
POSITION_KO = {
    "TOP": "탑", "JUNGLE": "정글", "MIDDLE": "미드",
    "BOTTOM": "원딜", "UTILITY": "서포터",
}
# platform -> op.gg 지역 코드
OPGG_REGION = {"kr": "kr", "na1": "na", "euw1": "euw", "jp1": "jp"}

REGION_CHOICES = [
    app_commands.Choice(name="한국 (KR)", value="kr"),
    app_commands.Choice(name="북미 (NA)", value="na1"),
    app_commands.Choice(name="서유럽 (EUW)", value="euw1"),
    app_commands.Choice(name="일본 (JP)", value="jp1"),
]

# 큐 ID -> 한글 게임 모드 이름
QUEUE_KO = {
    400: "일반 (드래프트)", 430: "일반 (블라인드)", 490: "빠른 대전",
    420: "솔로랭크", 440: "자유랭크", 450: "칼바람 나락",
    700: "격전", 900: "URF", 1900: "URF", 1700: "아레나", 1710: "아레나",
    0: "사용자 설정 게임",
}
TIER_KO = {
    "IRON": "아이언", "BRONZE": "브론즈", "SILVER": "실버", "GOLD": "골드",
    "PLATINUM": "플래티넘", "EMERALD": "에메랄드", "DIAMOND": "다이아몬드",
    "MASTER": "마스터", "GRANDMASTER": "그랜드마스터", "CHALLENGER": "챌린저",
}
DIVISION_NUM = {"I": "1", "II": "2", "III": "3", "IV": "4"}
TEAM_KO = {100: "🔵 블루팀", 200: "🔴 레드팀"}


def _queue_name(queue_id: int | None, fallback: str = "") -> str:
    return QUEUE_KO.get(queue_id, fallback or f"큐 {queue_id}")


def _format_rank(entries: list[dict], queue_type: str) -> str:
    """랭크 엔트리 목록에서 해당 큐의 '골드 2 · 45LP · 52% (120판)' 문자열을 만든다."""
    e = next((r for r in entries if r.get("queueType") == queue_type), None)
    if e is None:
        return "언랭"
    tier = TIER_KO.get(e["tier"], e["tier"])
    if e["tier"] not in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        tier += f" {DIVISION_NUM.get(e['rank'], e['rank'])}"
    total = e["wins"] + e["losses"]
    wr = round(e["wins"] / total * 100) if total else 0
    return f"{tier} · {e['leaguePoints']}LP · {wr}% ({total}판)"


class LoL(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # 같은 채널에 같은 게임 인게임 알림을 두 번 올리지 않도록 (친구끼리 같이 할 때)
        self._posted_live: deque[tuple[int, str]] = deque(maxlen=200)

    async def cog_load(self) -> None:
        self.auto_analysis_loop.start()

    async def cog_unload(self) -> None:
        self.auto_analysis_loop.cancel()

    # ────────────────────────── 공통 헬퍼 ──────────────────────────

    def _session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(ssl=lol_api.ssl_context())
        return aiohttp.ClientSession(connector=connector)

    def _opgg_view(self, game_name: str, tag_line: str, platform: str) -> discord.ui.View:
        oregion = OPGG_REGION.get(platform, "kr")
        url = f"https://www.op.gg/summoners/{oregion}/{quote(game_name)}-{quote(tag_line)}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="OP.GG에서 보기", url=url, emoji="🔗"))
        return view

    async def _send_profile(
        self, interaction: discord.Interaction,
        game_name: str, tag_line: str, platform: str,
    ) -> None:
        """전적 카드 이미지를 생성해 전송 (interaction은 이미 defer 상태여야 함)."""
        region_route = lol_api.PLATFORM_TO_REGION.get(platform, "asia")
        try:
            async with self._session() as session:
                account = await lol_api.get_account(
                    session, region_route, game_name, tag_line
                )
                puuid = account["puuid"]
                summoner = await lol_api.get_summoner(session, platform, puuid)
                ranked = await lol_api.get_ranked(session, platform, puuid)
                mastery = await lol_api.get_mastery(session, platform, puuid)
                match_ids = await lol_api.get_match_ids(
                    session, region_route, puuid, count=STATS_COUNT
                )

                sem = asyncio.Semaphore(CONCURRENCY)

                async def fetch(mid: str) -> dict:
                    async with sem:
                        return await lol_api.get_match(session, region_route, mid)

                matches = await asyncio.gather(*(fetch(mid) for mid in match_ids))
                await ddragon.load_champion_map(session)
                png = await self._build_card(
                    session, account, summoner, ranked, mastery, matches, puuid
                )
                view = self._opgg_view(account["gameName"], account["tagLine"], platform)
        except lol_api.RiotAPIError as e:
            await interaction.followup.send(f"❌ {e.message}")
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 알 수 없는 오류: `{type(e).__name__}`")
            raise

        file = discord.File(io.BytesIO(png), filename="lol.png")
        await interaction.followup.send(file=file, view=view)

    async def _build_card(
        self, session, account, summoner, ranked, mastery, matches, puuid
    ) -> bytes:
        # ── 헤더 (랭크) ──
        name = f"{account['gameName']}#{account['tagLine']}"
        level = summoner.get("summonerLevel", "?")
        solo = next(
            (r for r in ranked if r.get("queueType") == "RANKED_SOLO_5x5"), None
        )
        if solo:
            total = solo["wins"] + solo["losses"]
            wr = round(solo["wins"] / total * 100) if total else 0
            rank_line = f"{solo['tier']} {solo['rank']} · {solo['leaguePoints']} LP"
            sub_line = f"{solo['wins']}승 {solo['losses']}패 · 승률 {wr}%"
        else:
            rank_line = "솔로랭크 언랭"
            sub_line = ""
        header = {"name": name, "level": level, "rank_line": rank_line, "sub_line": sub_line}

        # ── 최근 게임 집계 ──
        stats = defaultdict(lambda: {"count": 0, "wins": 0})       # 챔프별
        positions = defaultdict(lambda: {"count": 0, "wins": 0})   # 라인별
        recent_rows_raw = []
        sum_cspm = sum_gpm = sum_kda = 0.0
        metric_games = 0

        for m in matches:
            p = next(
                (x for x in m["info"]["participants"] if x["puuid"] == puuid), None
            )
            if not p:
                continue
            recent_rows_raw.append(p)
            cid = p["championId"]
            win = p["win"]
            stats[cid]["count"] += 1
            stats[cid]["wins"] += 1 if win else 0

            pos = p.get("teamPosition") or p.get("individualPosition") or ""
            if pos and pos != "Invalid":
                positions[pos]["count"] += 1
                positions[pos]["wins"] += 1 if win else 0

            dur_min = m["info"].get("gameDuration", 0) / 60
            if dur_min >= 1:
                cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
                k, d, a = p["kills"], p["deaths"], p["assists"]
                sum_cspm += cs / dur_min
                sum_gpm += p.get("goldEarned", 0) / dur_min
                sum_kda += (k + a) / d if d else (k + a)
                metric_games += 1

        total_games = len(recent_rows_raw)

        # 필요한 챔프 이미지 미리 다운로드
        needed_ids = set(stats.keys())
        needed_ids.update(mm["championId"] for mm in mastery[:3])
        img_cache = {}
        for cid in needed_ids:
            info = ddragon.champ_info(cid)
            img_cache[cid] = await ddragon.get_champion_image(session, info["id"])

        def face(cid):
            return img_cache.get(cid)

        sections = []

        # ── 평균 지표 (분당 CS / 골드 / KDA) ──
        if metric_games:
            sections.append({
                "title": "평균 지표",
                "rows": [
                    {"face": False, "name": "분당 CS", "right": f"{sum_cspm / metric_games:.1f}"},
                    {"face": False, "name": "분당 골드", "right": f"{sum_gpm / metric_games:.0f}"},
                    {"face": False, "name": "평균 KDA", "right": f"{sum_kda / metric_games:.2f}"},
                ],
            })

        # ── 라인별 전적 ──
        pos_sorted = sorted(positions.items(), key=lambda kv: kv[1]["count"], reverse=True)
        pos_rows = []
        for pos, s in pos_sorted:
            wr = round(s["wins"] / s["count"] * 100) if s["count"] else 0
            losses = s["count"] - s["wins"]
            pos_rows.append({
                "face": False,
                "name": POSITION_KO.get(pos, pos),
                "right": f"{wr}%",
                "sub": f"{s['count']}게임 · {s['wins']}승 {losses}패",
            })
        if pos_rows:
            sections.append({"title": "라인별 전적", "rows": pos_rows})

        # ── 챔피언 숙련도 TOP 3 ──
        mastery_rows = []
        for mm in mastery[:3]:
            cid = mm["championId"]
            info = ddragon.champ_info(cid)
            mastery_rows.append({
                "img": face(cid), "name": info["name"],
                "right": f"M{mm['championLevel']}", "sub": f"{mm['championPoints']:,}점",
            })
        if mastery_rows:
            sections.append({"title": "챔피언 숙련도", "rows": mastery_rows})

        # ── 모스트 챔피언 (플레이 비율) ──
        most = sorted(stats.items(), key=lambda kv: kv[1]["count"], reverse=True)[:5]
        most_rows = []
        for cid, s in most:
            info = ddragon.champ_info(cid)
            pct = round(s["count"] / total_games * 100) if total_games else 0
            most_rows.append({
                "img": face(cid), "name": info["name"],
                "right": f"{pct}%", "sub": f"{s['count']}게임",
            })
        if most_rows:
            sections.append({"title": f"모스트 챔피언 (최근 {total_games}게임)", "rows": most_rows})

        # ── 잘 이기는 챔피언 (승률) ──
        candidates = [(c, s) for c, s in stats.items() if s["count"] >= 2]
        if len(candidates) < 3:
            candidates = list(stats.items())
        best = sorted(
            candidates,
            key=lambda kv: (kv[1]["wins"] / kv[1]["count"], kv[1]["count"]),
            reverse=True,
        )[:5]
        best_rows = []
        for cid, s in best:
            info = ddragon.champ_info(cid)
            wr = round(s["wins"] / s["count"] * 100) if s["count"] else 0
            losses = s["count"] - s["wins"]
            best_rows.append({
                "img": face(cid), "name": info["name"],
                "right": f"{wr}%", "sub": f"{s['wins']}승 {losses}패",
            })
        if best_rows:
            sections.append({"title": "잘 이기는 챔피언", "rows": best_rows})

        # ── 최근 전적 ──
        recent_rows = []
        for p in recent_rows_raw[:RECENT_COUNT]:
            cid = p["championId"]
            info = ddragon.champ_info(cid)
            k, d, a = p["kills"], p["deaths"], p["assists"]
            kda = (k + a) / d if d else (k + a)
            recent_rows.append({
                "img": face(cid), "name": info["name"],
                "right": f"{k}/{d}/{a}", "sub": f"KDA {kda:.2f}",
                "result": "win" if p["win"] else "loss",
            })
        if recent_rows:
            sections.append({"title": "최근 전적", "rows": recent_rows})

        return await asyncio.to_thread(image_card.render_card, header, sections)

    # ────────────────────────── 명령어 ──────────────────────────

    @app_commands.command(name="lol", description="롤 전적을 조회합니다 (전적 카드 이미지).")
    @app_commands.describe(riot_id="라이엇 ID (예: Hide on bush#KR1)", region="지역 (기본 kr)")
    @app_commands.choices(region=REGION_CHOICES)
    async def lol(self, interaction: discord.Interaction, riot_id: str, region: str = "kr") -> None:
        parsed = await self._parse_riot_id(interaction, riot_id)
        if parsed is None:
            return
        game_name, tag_line = parsed
        await interaction.response.defer()
        await self._send_profile(interaction, game_name, tag_line, region)

    @app_commands.command(name="내전적", description="연결된 내 롤 계정의 전적을 조회합니다.")
    async def my_stats(self, interaction: discord.Interaction) -> None:
        linked = database.get_linked(interaction.user.id)
        if not linked:
            await interaction.response.send_message(
                "먼저 `/링크`로 롤 계정을 연결해주세요.", ephemeral=True
            )
            return
        await interaction.response.defer()
        await self._send_profile(
            interaction, linked["game_name"], linked["tag_line"], linked["platform"]
        )

    @app_commands.command(name="링크", description="내 디스코드에 롤 계정을 연결합니다.")
    @app_commands.describe(riot_id="라이엇 ID (예: Hide on bush#KR1)", region="지역 (기본 kr)")
    @app_commands.choices(region=REGION_CHOICES)
    async def link(self, interaction: discord.Interaction, riot_id: str, region: str = "kr") -> None:
        parsed = await self._parse_riot_id(interaction, riot_id)
        if parsed is None:
            return
        game_name, tag_line = parsed
        region_route = lol_api.PLATFORM_TO_REGION.get(region, "asia")
        await interaction.response.defer(ephemeral=True)
        try:
            async with self._session() as session:
                account = await lol_api.get_account(
                    session, region_route, game_name, tag_line
                )
        except lol_api.RiotAPIError as e:
            await interaction.followup.send(f"❌ {e.message}", ephemeral=True)
            return
        database.link_account(
            interaction.user.id, account["gameName"], account["tagLine"],
            account["puuid"], region,
        )
        await interaction.followup.send(
            f"✅ **{account['gameName']}#{account['tagLine']}** 계정을 연결했어요!\n"
            f"이제 `/내전적`으로 바로 조회하고, `/자동분석 켜기`로 게임 종료 자동 분석도 켤 수 있어요.",
            ephemeral=True,
        )

    @app_commands.command(name="자동분석", description="게임이 끝나면 이 채널에 방금 판 분석을 자동 게시합니다.")
    @app_commands.describe(설정="켜기 / 끄기")
    @app_commands.choices(설정=[
        app_commands.Choice(name="켜기", value="on"),
        app_commands.Choice(name="끄기", value="off"),
    ])
    async def auto_analysis(self, interaction: discord.Interaction, 설정: str) -> None:
        linked = database.get_linked(interaction.user.id)
        if not linked:
            await interaction.response.send_message(
                "먼저 `/링크`로 롤 계정을 연결해주세요.", ephemeral=True
            )
            return
        if 설정 == "on":
            database.set_auto_channel(interaction.user.id, interaction.channel_id)
            await interaction.response.send_message(
                "✅ 자동 분석을 켰어요! 이 채널에 게임이 시작되면 참가자 정보를, "
                "끝나면 방금 판 분석을 올려드릴게요. (감지까지 최대 3분)"
            )
        else:
            database.set_auto_channel(interaction.user.id, None)
            await interaction.response.send_message("🛑 자동 분석을 껐어요.", ephemeral=True)

    @app_commands.command(name="인게임", description="진행 중인 게임의 참가자 티어/승률을 봅니다.")
    @app_commands.describe(
        riot_id="라이엇 ID (예: Hide on bush#KR1). 비우면 연결된 내 계정",
        region="지역 (기본 kr)",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def live_game(
        self, interaction: discord.Interaction, riot_id: str | None = None, region: str = "kr"
    ) -> None:
        if riot_id:
            parsed = await self._parse_riot_id(interaction, riot_id)
            if parsed is None:
                return
            game_name, tag_line = parsed
            platform = region
            puuid = None
        else:
            linked = database.get_linked(interaction.user.id)
            if not linked:
                await interaction.response.send_message(
                    "이름#태그를 입력하거나, 먼저 `/링크`로 내 롤 계정을 연결해주세요.",
                    ephemeral=True,
                )
                return
            game_name, tag_line = linked["game_name"], linked["tag_line"]
            platform, puuid = linked["platform"], linked["puuid"]

        await interaction.response.defer()
        try:
            async with self._session() as session:
                if puuid is None:
                    region_route = lol_api.PLATFORM_TO_REGION.get(platform, "asia")
                    account = await lol_api.get_account(session, region_route, game_name, tag_line)
                    puuid = account["puuid"]
                    game_name, tag_line = account["gameName"], account["tagLine"]
                game = await lol_api.get_active_game(session, platform, puuid)
                if game is None:
                    await interaction.followup.send(
                        f"🎮 **{discord.utils.escape_markdown(game_name)}#{tag_line}** 님은 지금 게임 중이 아니에요."
                    )
                    return
                embed = await self._live_game_embed(session, game, platform, puuid)
        except lol_api.RiotAPIError as e:
            await interaction.followup.send(f"❌ {e.message}")
            return
        await interaction.followup.send(embed=embed)

    async def _live_game_embed(
        self, session, game: dict, platform: str, highlight_puuid: str | None
    ) -> discord.Embed:
        """진행 중 게임 정보를 팀별 참가자 목록(챔피언·이름·티어) 임베드로 만든다."""
        await ddragon.load_champion_map(session)
        queue_id = game.get("gameQueueConfigId")
        queue_type = "RANKED_FLEX_SR" if queue_id == 440 else "RANKED_SOLO_5x5"
        rank_label = "자유랭크" if queue_id == 440 else "솔로랭크"
        participants = game.get("participants", [])

        sem = asyncio.Semaphore(CONCURRENCY)

        async def rank_of(p: dict) -> str:
            if p.get("bot") or not p.get("puuid"):
                return "봇"
            async with sem:
                try:
                    entries = await lol_api.get_ranked(session, platform, p["puuid"])
                except lol_api.RiotAPIError:
                    return "?"
            return _format_rank(entries, queue_type)

        ranks = await asyncio.gather(*(rank_of(p) for p in participants))

        teams: dict[int, list[str]] = defaultdict(list)
        for p, rank in zip(participants, ranks):
            champ = ddragon.champ_info(p.get("championId", 0))["name"]
            name = discord.utils.escape_markdown(p.get("riotId") or "알 수 없음")
            line = f"**{champ}** · {name}\n└ {rank}"
            if highlight_puuid and p.get("puuid") == highlight_puuid:
                line = f"👉 {line}"
            teams[p.get("teamId", 0)].append(line)

        start_ms = game.get("gameStartTime") or 0
        elapsed = f"{int((time.time() * 1000 - start_ms) / 60000)}분 진행 중" if start_ms > 0 else "로딩 중"
        embed = discord.Embed(
            title=f"🎮 인게임 · {_queue_name(queue_id, game.get('gameMode', ''))}",
            description=f"{elapsed} · 티어는 {rank_label} 기준",
            color=discord.Color.gold(),
        )
        for team_id in sorted(teams):
            embed.add_field(
                name=TEAM_KO.get(team_id, f"팀 {team_id}"),
                value="\n".join(teams[team_id])[:1024],
                inline=True,
            )
        embed.set_footer(text="powered by Riot Games API")
        return embed

    async def _parse_riot_id(
        self, interaction: discord.Interaction, riot_id: str
    ) -> tuple[str, str] | None:
        """API 키/형식을 검증하고 (game_name, tag_line)을 반환. 문제 있으면 안내 후 None."""
        if not config.RIOT_API_KEY:
            await interaction.response.send_message(
                "⚠️ Riot API 키가 설정되지 않았어요. `.env`에 `RIOT_API_KEY`를 넣어주세요.",
                ephemeral=True,
            )
            return None
        if "#" not in riot_id:
            await interaction.response.send_message(
                "형식이 틀렸어요. `이름#태그` 형식으로 입력해주세요. 예: `Hide on bush#KR1`",
                ephemeral=True,
            )
            return None
        game_name, tag_line = (s.strip() for s in riot_id.rsplit("#", 1))
        return game_name, tag_line

    # ────────────────────── 백그라운드 자동 분석 ──────────────────────

    @tasks.loop(minutes=3)
    async def auto_analysis_loop(self) -> None:
        accounts = database.all_auto_accounts()
        if not accounts:
            return
        try:
            async with self._session() as session:
                await ddragon.load_champion_map(session)
                for acc in accounts:
                    try:
                        await self._check_live_game(session, acc)
                    except Exception as e:
                        log.warning("live-game check failed: %s", e)
                    try:
                        await self._check_new_game(session, acc)
                    except Exception as e:
                        log.warning("auto-analysis check failed: %s", e)
        except Exception as e:
            log.warning("auto-analysis loop error: %s", e)

    @auto_analysis_loop.before_loop
    async def _before_auto(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_live_game(self, session, acc: dict) -> None:
        """새 게임이 시작됐으면 자동분석 채널에 인게임 정보를 올린다 (게임당 1회)."""
        game = await lol_api.get_active_game(session, acc["platform"], acc["puuid"])
        if game is None:
            return
        game_id = str(game.get("gameId"))
        if game_id == acc.get("last_live_game_id"):
            return
        database.update_last_live_game(acc["discord_id"], game_id)

        channel = self.bot.get_channel(acc["auto_channel_id"])
        if channel is None:
            return
        key = (channel.id, game_id)
        if key in self._posted_live:  # 같은 채널의 친구가 같은 게임에 있으면 이미 올렸음
            return
        self._posted_live.append(key)
        embed = await self._live_game_embed(session, game, acc["platform"], acc["puuid"])
        await channel.send(
            content=f"<@{acc['discord_id']}> 게임이 시작됐어요! 이번 판 참가자 정보예요 ⚔️",
            embed=embed,
        )

    async def _check_new_game(self, session, acc: dict) -> None:
        region_route = lol_api.PLATFORM_TO_REGION.get(acc["platform"], "asia")
        ids = await lol_api.get_match_ids(session, region_route, acc["puuid"], count=1)
        if not ids:
            return
        latest = ids[0]
        # 최초 등록 시엔 기준선만 잡고 게시하지 않음
        if acc["last_match_id"] is None:
            database.update_last_match(acc["discord_id"], latest)
            return
        if latest == acc["last_match_id"]:
            return

        match = await lol_api.get_match(session, region_route, latest)
        database.update_last_match(acc["discord_id"], latest)

        channel = self.bot.get_channel(acc["auto_channel_id"])
        if channel is None:
            return
        p = next(
            (x for x in match["info"]["participants"] if x["puuid"] == acc["puuid"]), None
        )
        if p is None:
            return
        comment = await self._ai_comment(match, p)
        embed = self._analysis_embed(match, p, comment)
        await channel.send(content=f"<@{acc['discord_id']}> 방금 게임 분석이 나왔어요! 🎮", embed=embed)

    async def _ai_comment(self, match: dict, p: dict) -> str | None:
        """게임 결과를 AI(할아버지 말투)에게 보내 짧은 피드백을 받는다. 실패하면 None."""
        if not ai.is_configured():
            return None
        info = match["info"]
        dur_min = (info.get("gameDuration", 0) / 60) or 1
        team = [x for x in info["participants"] if x.get("teamId") == p.get("teamId")]
        team_kills = sum(x["kills"] for x in team) or 1
        kp = round((p["kills"] + p["assists"]) / team_kills * 100)
        dmg_rank = 1 + sum(
            1 for x in team
            if x.get("totalDamageDealtToChampions", 0) > p.get("totalDamageDealtToChampions", 0)
        )
        cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
        pos = p.get("teamPosition") or p.get("individualPosition") or ""
        prompt = (
            "방금 끝난 리그 오브 레전드 게임에서 이 손주가 낸 기록이다. "
            "할아버지 말투로 2~3문장, 150자 이내로 잘한 점이나 아쉬운 점을 콕 집어 "
            "칭찬하거나 조언해 주거라. 숫자를 줄줄이 나열하지는 말고 핵심 한두 개만 짚어라.\n"
            f"- 게임 모드: {_queue_name(info.get('queueId'), info.get('gameMode', ''))}\n"
            f"- 챔피언: {ddragon.champ_info(p['championId'])['name']}\n"
            f"- 포지션: {POSITION_KO.get(pos, pos or '알 수 없음')}\n"
            f"- 결과: {'승리' if p['win'] else '패배'}\n"
            f"- KDA: {p['kills']}/{p['deaths']}/{p['assists']}\n"
            f"- 킬 관여율: {kp}%\n"
            f"- 분당 CS: {cs / dur_min:.1f}\n"
            f"- 분당 골드: {p.get('goldEarned', 0) / dur_min:.0f}\n"
            f"- 챔피언 피해량: {p.get('totalDamageDealtToChampions', 0):,} (팀 내 {dmg_rank}위)\n"
            f"- 시야 점수: {p.get('visionScore', 0)}\n"
            f"- 게임 시간: {int(dur_min)}분"
        )
        try:
            text = await ai.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            log.warning("AI 한마디 생성 실패: %s", e)
            return None
        return text[:1000]

    def _analysis_embed(self, match: dict, p: dict, comment: str | None) -> discord.Embed:
        info = ddragon.champ_info(p["championId"])
        dur_min = (match["info"].get("gameDuration", 0) / 60) or 1
        cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
        cspm = cs / dur_min
        gpm = p.get("goldEarned", 0) / dur_min
        k, d, a = p["kills"], p["deaths"], p["assists"]
        kda = (k + a) / d if d else (k + a)
        win = p["win"]

        embed = discord.Embed(
            title=f"{'🏆 승리' if win else '💀 패배'} · {info['name']}",
            color=discord.Color.blue() if win else discord.Color.red(),
        )
        embed.add_field(name="KDA", value=f"{k}/{d}/{a} ({kda:.2f})")
        embed.add_field(name="분당 CS", value=f"{cspm:.1f}")
        embed.add_field(name="분당 골드", value=f"{gpm:.0f}")
        embed.add_field(
            name="챔피언에게 가한 피해",
            value=f"{p.get('totalDamageDealtToChampions', 0):,}",
        )
        embed.add_field(name="플레이 시간", value=f"{int(dur_min)}분")
        if comment:
            embed.add_field(name="👴 할아버지 한마디", value=comment, inline=False)
        else:
            embed.add_field(name="한줄평", value=self._evaluate(win, kda, cspm), inline=False)

        url = ddragon.image_url(info["id"])
        if url:
            embed.set_thumbnail(url=url)
        embed.set_footer(text="powered by Riot Games API")
        return embed

    @staticmethod
    def _evaluate(win: bool, kda: float, cspm: float) -> str:
        if win and kda >= 4:
            return "완벽한 캐리였어요! 🔥"
        if win:
            return "깔끔한 승리! 이 기세 이어가요 👍"
        if kda < 1.5:
            return "힘든 한 판이었네요. 다음 판 힘내요 😢"
        if cspm >= 7:
            return "졌지만 CS 수급은 훌륭했어요. 아깝네요!"
        return "아쉬운 패배. 다음 판 반드시 설욕해요 💪"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoL(bot))

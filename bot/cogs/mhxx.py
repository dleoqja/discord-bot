"""몬스터헌터 더블크로스(MHXX/MHGU) 방어구 세트 빌더 Cog.

/armorset 원하는 스킬을 고르면 조건을 만족하는 방어구 조합을 짜준다.
데이터 출처: gatheringhallstudios/MHGenDatabase (실데이터).
"""
from __future__ import annotations

import functools

import discord
from discord import app_commands
from discord.ext import commands

from bot.mhxx import data as mhxx_data
from bot.mhxx.data import (
    GENDER_BOTH, GENDER_FEMALE, GENDER_MALE,
    HT_BLADEMASTER, HT_GUNNER, PART_KO, PARTS,
)
from bot.mhxx.solver import Charm, SetResult, Target, solve

_SEP = "|"


@functools.lru_cache(maxsize=1)
def _all_skill_choices() -> list[tuple[str, str, str]]:
    """(표시라벨, 검색용문자열, value='tree_id|points') 목록.

    방어구에 많이 붙는 '인기 스킬' 순으로 정렬한다. 디스코드 자동완성은
    한 번에 25개까지만 보여주므로, 아무것도 입력하지 않았을 때 흔히 쓰는
    스킬(공격/간파/약점특효 등)이 먼저 뜨도록 한다.
    """
    data = mhxx_data.get_data()

    # 인기도 = 해당 트리에 양수 포인트를 주는 방어구 개수
    popularity: dict[str, int] = {}
    for part in PARTS:
        for piece in data.armor_by_part.get(part, []):
            for tid, val in piece.skills.items():
                if val > 0:
                    popularity[tid] = popularity.get(tid, 0) + 1

    rows: list[tuple[int, str, int, str, str, str]] = []
    for tree_id, tree in data.trees.items():
        for act in tree.activations:
            label = f"{tree.label} · {act.name} ({act.points}p)"
            search = f"{tree.en} {tree.ko or ''} {act.name}".lower()
            rows.append((
                popularity.get(tree_id, 0), tree_id, act.points,
                label[:100], search, f"{tree_id}{_SEP}{act.points}",
            ))

    # 인기도 내림차순 → 같은 트리끼리 묶고 → 필요 포인트 오름차순
    rows.sort(key=lambda r: (-r[0], r[1], r[2]))
    return [(label, search, value) for _, _, _, label, search, value in rows]


def _parse_target(value: str | None) -> Target | None:
    if not value or _SEP not in value:
        return None
    tree_id, _, pts = value.partition(_SEP)
    if not pts.isdigit() or tree_id not in mhxx_data.get_data().trees:
        return None
    return Target(tree_id=tree_id, required_points=int(pts))


async def _skill_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    hits = [
        app_commands.Choice(name=label, value=value)
        for label, search, value in _all_skill_choices()
        if cur in search or cur in label.lower()
    ]
    return hits[:25]


@functools.lru_cache(maxsize=1)
def _all_tree_choices() -> list[tuple[str, str, str]]:
    """호석 스킬용 (트리 라벨, 검색어, tree_id) 목록. 대중적인 트리 순."""
    data = mhxx_data.get_data()
    popularity: dict[str, int] = {}
    for part in PARTS:
        for piece in data.armor_by_part.get(part, []):
            for tid, val in piece.skills.items():
                if val > 0:
                    popularity[tid] = popularity.get(tid, 0) + 1
    rows = [
        (popularity.get(tid, 0), tree.label[:100], f"{tree.en} {tree.ko or ''}".lower(), tid)
        for tid, tree in data.trees.items()
    ]
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [(label, search, tid) for _, label, search, tid in rows]


async def _tree_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    hits = [
        app_commands.Choice(name=label, value=tid)
        for label, search, tid in _all_tree_choices()
        if cur in search or cur in label.lower()
    ]
    return hits[:25]


class MHXX(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="armorset",
        description="MHXX: 원하는 스킬로 방어구 세트를 짜줍니다.",
    )
    @app_commands.describe(
        skill1="원하는 스킬 (필수)",
        skill2="추가 스킬 (선택)",
        skill3="추가 스킬 (선택)",
        skill4="추가 스킬 (선택)",
        skill5="추가 스킬 (선택)",
        skill6="추가 스킬 (선택)",
        무기="검사 / 거너 (기본: 검사)",
        성별="장비 성별 제한 (기본: 공용 방어구만)",
        호석슬롯="가진 호석의 슬롯 수 0~3 (기본: 0)",
        호석스킬1="호석이 주는 스킬 ①",
        호석포인트1="호석 스킬 ①의 포인트 (예: 5)",
        호석스킬2="호석이 주는 스킬 ②",
        호석포인트2="호석 스킬 ②의 포인트 (예: 3)",
    )
    @app_commands.choices(
        무기=[
            app_commands.Choice(name="검사", value=HT_BLADEMASTER),
            app_commands.Choice(name="거너", value=HT_GUNNER),
        ],
        성별=[
            app_commands.Choice(name="공용만", value=GENDER_BOTH),
            app_commands.Choice(name="남", value=GENDER_MALE),
            app_commands.Choice(name="여", value=GENDER_FEMALE),
        ],
    )
    @app_commands.autocomplete(
        skill1=_skill_autocomplete,
        skill2=_skill_autocomplete,
        skill3=_skill_autocomplete,
        skill4=_skill_autocomplete,
        skill5=_skill_autocomplete,
        skill6=_skill_autocomplete,
        호석스킬1=_tree_autocomplete,
        호석스킬2=_tree_autocomplete,
    )
    async def armorset(
        self,
        interaction: discord.Interaction,
        skill1: str,
        skill2: str | None = None,
        skill3: str | None = None,
        skill4: str | None = None,
        skill5: str | None = None,
        skill6: str | None = None,
        무기: int = HT_BLADEMASTER,
        성별: int = GENDER_BOTH,
        호석슬롯: app_commands.Range[int, 0, 3] = 0,
        호석스킬1: str | None = None,
        호석포인트1: app_commands.Range[int, -10, 20] = 0,
        호석스킬2: str | None = None,
        호석포인트2: app_commands.Range[int, -10, 20] = 0,
    ) -> None:
        # 같은 계통 중복 입력 시 높은 요구치만 채택
        targets: dict[str, Target] = {}
        for raw in (skill1, skill2, skill3, skill4, skill5, skill6):
            t = _parse_target(raw)
            if t is None:
                continue
            ex = targets.get(t.tree_id)
            if ex is None or t.required_points > ex.required_points:
                targets[t.tree_id] = t
        target_list = list(targets.values())

        if not target_list:
            await interaction.response.send_message(
                "스킬을 자동완성 목록에서 골라주세요.", ephemeral=True
            )
            return

        # 호석 스킬 구성
        trees = mhxx_data.get_data().trees
        charm_skills: dict[str, int] = {}
        for tid, pts in ((호석스킬1, 호석포인트1), (호석스킬2, 호석포인트2)):
            if tid and tid in trees and pts:
                charm_skills[tid] = charm_skills.get(tid, 0) + pts

        # 탐색이 길어질 수 있으므로 응답 지연 처리
        await interaction.response.defer(thinking=True)

        data = mhxx_data.get_data()
        charm = Charm(skills=charm_skills, slots=호석슬롯)
        results = solve(data, target_list, hunter_type=무기, gender=성별,
                        charm=charm, max_results=6)

        wanted = ", ".join(
            f"{data.tree_ko(t.tree_id)} {t.required_points}p" for t in target_list
        )
        ht_ko = "검사" if 무기 == HT_BLADEMASTER else "거너"
        head = f"**원하는 스킬:** {wanted}\n**무기:** {ht_ko}"
        if charm_skills or 호석슬롯:
            charm_txt = ", ".join(
                f"{data.tree_ko(tid)}{pts:+d}" for tid, pts in charm_skills.items()
            )
            if 호석슬롯:
                charm_txt = f"{charm_txt} · {호석슬롯}슬롯" if charm_txt else f"{호석슬롯}슬롯"
            head += f" · **호석:** {charm_txt}"

        if not results:
            embed = discord.Embed(
                title="🛡️ 방어구 세트 빌더",
                description=(
                    f"{head}\n\n"
                    "😢 이 조합을 만족하는 세트를 찾지 못했어요.\n"
                    "스킬 수를 줄이거나, 호석 슬롯을 늘려보세요. "
                    "실제 게임에선 호석(護石)으로 마지막 스킬을 채우는 경우가 많습니다."
                ),
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(
            title="🛡️ 방어구 세트 빌더",
            description=head,
            color=discord.Color.green(),
        )
        for idx, res in enumerate(results, start=1):
            embed.add_field(name=f"추천 세트 {idx}", value=_format_set(data, res), inline=False)
        embed.set_footer(text="⭐요청 스킬 · ➕보너스 스킬 | 데이터: MHGenDatabase(MHGU)")
        await interaction.followup.send(embed=embed)


def _format_set(data: mhxx_data.GameData, res: SetResult) -> str:
    lines: list[str] = []
    for part in PARTS:
        piece = res.pieces.get(part)
        lines.append(f"`{PART_KO[part]:<2}` {piece.name if piece else '— (아무거나)'}")

    if res.decorations:
        deco_txt = ", ".join(f"{d.name}×{c}" for d, c in res.decorations)
        lines.append(f"💠 {_clip(deco_txt, 300)}")

    requested = [f"{label} · {name}" for label, name, is_req in res.activations if is_req]
    bonus = [name for label, name, is_req in res.activations if not is_req]
    lines.append(f"⭐ {' / '.join(requested)}")
    if bonus:
        shown = bonus[:12]
        extra = f" 외 {len(bonus) - len(shown)}개" if len(bonus) > len(shown) else ""
        lines.append(f"➕ {_clip(', '.join(shown), 300)}{extra}")
    lines.append(f"🔧 슬롯 {res.used_slots}/{res.total_slots} · 🛡️ 방어력 {res.total_defense}")
    return _clip("\n".join(lines), 1024)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MHXX(bot))

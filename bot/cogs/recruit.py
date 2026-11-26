"""파티 모집 Cog.

/모집 게임 시간 인원  → 모집 글을 올리고, 버튼으로 참가/나가기.
- 모집한 사람은 자동으로 첫 참가자가 된다.
- 인원이 다 차면 참가 버튼이 잠기고, 참가자 전원을 멘션해 알린다.
- 버튼 상태는 DB(recruits)에 저장되어 봇이 재시작돼도 계속 동작한다.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot import database

log = logging.getLogger("bot.recruit")

JOIN_ID = "recruit:join"
LEAVE_ID = "recruit:leave"


def build_embed(rec: dict) -> discord.Embed:
    members = rec["participants"]
    full = len(members) >= rec["max_players"]
    embed = discord.Embed(
        title=f"{'✅ 모집 완료' if full else '🎮 파티 모집'} · {rec['game']}",
        color=discord.Color.dark_grey() if full else discord.Color.green(),
    )
    embed.add_field(name="🕘 시간", value=rec["time_text"])
    embed.add_field(name="👥 인원", value=f"{len(members)} / {rec['max_players']}")
    embed.add_field(name="📣 모집자", value=f"<@{rec['host_id']}>")
    embed.add_field(
        name="참가자",
        value="\n".join(f"{i}. <@{uid}>" for i, uid in enumerate(members, 1)) or "아직 없어요",
        inline=False,
    )
    embed.set_footer(text="아래 버튼으로 참가하거나 나갈 수 있어요.")
    return embed


class RecruitView(discord.ui.View):
    """모든 모집 글이 공유하는 영구 View. 어떤 글인지는 interaction.message.id 로 찾는다."""

    def __init__(self, full: bool = False) -> None:
        super().__init__(timeout=None)
        self.join.disabled = full

    async def _load(self, interaction: discord.Interaction) -> dict | None:
        rec = database.get_recruit(interaction.message.id)
        if rec is None:
            await interaction.response.send_message(
                "이 모집 글 정보를 찾을 수 없어요. 새로 `/모집` 해주세요.", ephemeral=True
            )
        return rec

    async def _update(self, interaction: discord.Interaction, rec: dict) -> None:
        full = len(rec["participants"]) >= rec["max_players"]
        await interaction.response.edit_message(embed=build_embed(rec), view=RecruitView(full))

    @discord.ui.button(label="참가", emoji="✋", style=discord.ButtonStyle.success, custom_id=JOIN_ID)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rec = await self._load(interaction)
        if rec is None:
            return
        uid = interaction.user.id
        members = rec["participants"]
        if uid in members:
            await interaction.response.send_message("이미 참가했어요!", ephemeral=True)
            return
        if len(members) >= rec["max_players"]:
            await interaction.response.send_message("인원이 다 찼어요 😢", ephemeral=True)
            return

        members.append(uid)
        database.set_recruit_participants(rec["message_id"], members)
        await self._update(interaction, rec)

        if len(members) >= rec["max_players"]:
            mentions = " ".join(f"<@{m}>" for m in members)
            await interaction.followup.send(
                f"🎉 **{rec['game']}** 인원이 다 모였어요! ({rec['time_text']})\n{mentions}"
            )

    @discord.ui.button(label="나가기", emoji="🚪", style=discord.ButtonStyle.danger, custom_id=LEAVE_ID)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rec = await self._load(interaction)
        if rec is None:
            return
        uid = interaction.user.id
        if uid not in rec["participants"]:
            await interaction.response.send_message("참가하지 않은 모집이에요.", ephemeral=True)
            return
        rec["participants"].remove(uid)
        database.set_recruit_participants(rec["message_id"], rec["participants"])
        await self._update(interaction, rec)


class Recruit(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        # 재시작 후에도 기존 모집 글의 버튼이 동작하도록 영구 View 등록
        self.bot.add_view(RecruitView())

    @app_commands.command(name="모집", description="같이 게임할 파티원을 모집합니다.")
    @app_commands.describe(
        게임="무슨 게임? (예: 롤 칼바람)",
        시간="몇 시에? (예: 오늘 밤 9시)",
        인원="총 몇 명? (나 포함)",
    )
    async def recruit(
        self,
        interaction: discord.Interaction,
        게임: app_commands.Range[str, 1, 100],
        시간: app_commands.Range[str, 1, 100],
        인원: app_commands.Range[int, 2, 50],
    ) -> None:
        rec = {
            "host_id": interaction.user.id,
            "game": 게임,
            "time_text": 시간,
            "max_players": 인원,
            "participants": [interaction.user.id],
        }
        await interaction.response.send_message(embed=build_embed(rec), view=RecruitView())
        msg = await interaction.original_response()
        database.create_recruit(
            msg.id, msg.channel.id, rec["host_id"], 게임, 시간, 인원, rec["participants"]
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Recruit(bot))

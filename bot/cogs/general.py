"""일반 명령어: ping, 포인트 조회, 랭킹."""
import discord
from discord import app_commands
from discord.ext import commands

from bot import database


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="봇 응답 속도를 확인합니다.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! ({latency_ms}ms)")

    @app_commands.command(name="points", description="내 포인트를 확인합니다.")
    async def points(self, interaction: discord.Interaction) -> None:
        pts = database.get_points(interaction.user.id)
        await interaction.response.send_message(f"💰 현재 포인트: **{pts}점**")

    @app_commands.command(name="rank", description="포인트 랭킹 TOP 5를 봅니다.")
    async def rank(self, interaction: discord.Interaction) -> None:
        rows = database.top_users(5)
        if not rows:
            await interaction.response.send_message("아직 랭킹 데이터가 없어요.")
            return

        lines = []
        for i, (user_id, pts) in enumerate(rows, start=1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} <@{user_id}> — {pts}점")

        embed = discord.Embed(title="🏆 포인트 랭킹", description="\n".join(lines))
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))

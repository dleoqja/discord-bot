"""미니게임 Cog: 가위바위보 (버튼 UI + 포인트 지급)."""
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot import database

CHOICES = {"rock": "✊ 바위", "paper": "✋ 보", "scissors": "✌️ 가위"}
# 키가 값을 이긴다
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
WIN_POINTS = 10


class RPSView(discord.ui.View):
    """가위바위보 버튼 3개를 담은 인터랙션 View."""

    def __init__(self, player_id: int) -> None:
        super().__init__(timeout=30)
        self.player_id = player_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 게임을 시작한 사람만 버튼을 누를 수 있게 제한
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "이 게임은 당신 것이 아니에요! `/rps`로 직접 시작해보세요.",
                ephemeral=True,
            )
            return False
        return True

    async def _play(self, interaction: discord.Interaction, player_choice: str) -> None:
        bot_choice = random.choice(list(CHOICES))

        if player_choice == bot_choice:
            result = "🤝 비겼어요!"
        elif BEATS[player_choice] == bot_choice:
            total = database.add_points(interaction.user.id, WIN_POINTS)
            result = f"🎉 이겼어요! +{WIN_POINTS}점 (총 {total}점)"
        else:
            result = "😢 졌어요..."

        msg = (
            f"당신: {CHOICES[player_choice]}\n"
            f"봇: {CHOICES[bot_choice]}\n\n"
            f"{result}"
        )
        # 버튼 비활성화 후 결과 표시
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=msg, view=self)
        self.stop()

    @discord.ui.button(label="바위", emoji="✊", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._play(interaction, "rock")

    @discord.ui.button(label="보", emoji="✋", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._play(interaction, "paper")

    @discord.ui.button(label="가위", emoji="✌️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._play(interaction, "scissors")


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="rps", description="봇과 가위바위보! 이기면 포인트 획득")
    async def rps(self, interaction: discord.Interaction) -> None:
        view = RPSView(player_id=interaction.user.id)
        await interaction.response.send_message(
            "가위바위보! 버튼을 골라주세요 👇", view=view
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))

"""AI 어시스턴트 Cog — Groq 무료 API 기반 (.env 의 GROQ_API_KEY 필요).

- /ai [질문]     : 단발 질문답변 (문맥 없음)
- 봇을 멘션        : 대화 (채널별 최근 문맥 유지)
"""
import logging
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from bot import ai

log = logging.getLogger("bot.assistant")

MAX_TURNS = 8        # 채널별로 기억할 최근 메시지 수 (user+assistant 합쳐서)
MAX_INPUT = 1500     # 사용자 입력 최대 길이
DISCORD_LIMIT = 2000  # 디스코드 메시지 글자 제한

NOT_CONFIGURED_MSG = "⚠️ AI 키가 설정되지 않았어요. 봇 관리자가 `.env`에 `GROQ_API_KEY`를 넣어야 해요."
FAILED_MSG = "⚠️ 지금 AI 응답을 받지 못했어요. 무료 사용 한도에 걸렸을 수 있으니 잠시 후 다시 시도해주세요."


def _error_msg() -> str:
    return FAILED_MSG if ai.is_configured() else NOT_CONFIGURED_MSG


def _chunks(text: str, size: int = DISCORD_LIMIT) -> list[str]:
    """디스코드 2000자 제한에 맞춰 응답을 분할한다."""
    text = text.strip()
    if not text:
        return ["(빈 응답)"]
    return [text[i : i + size] for i in range(0, len(text), size)]


class Assistant(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # 채널 id -> 최근 대화 히스토리 (deque, 최대 MAX_TURNS개)
        self.history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_TURNS))

    async def _ask(self, channel_id: int, user_text: str, *, use_history: bool) -> str:
        user_text = user_text[:MAX_INPUT]
        msgs = list(self.history[channel_id]) if use_history else []
        msgs.append({"role": "user", "content": user_text})

        answer = await ai.chat(msgs)

        if use_history:
            self.history[channel_id].append({"role": "user", "content": user_text})
            self.history[channel_id].append({"role": "assistant", "content": answer})
        return answer

    # ────────────────────────── 슬래시 명령어 ──────────────────────────

    @app_commands.command(name="ai", description="뿌왁스볼에게 질문합니다.")
    @app_commands.describe(질문="물어볼 내용")
    async def ai_cmd(self, interaction: discord.Interaction, 질문: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            answer = await self._ask(interaction.channel_id, 질문, use_history=False)
        except ai.AIError:
            await interaction.followup.send(_error_msg())
            return
        chunks = _chunks(answer)
        await interaction.followup.send(chunks[0])
        for c in chunks[1:]:
            await interaction.followup.send(c)

    # ────────────────────────── 멘션 대화 ──────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # 봇 자신/다른 봇 메시지는 무시
        if message.author.bot:
            return
        # 봇을 직접 멘션한 경우에만 반응
        if self.bot.user is None or self.bot.user not in message.mentions:
            return

        content = (
            message.content.replace(f"<@{self.bot.user.id}>", "")
            .replace(f"<@!{self.bot.user.id}>", "")
            .strip()
        )
        if not content:
            await message.reply("네, 무엇이든 물어보세요! 🤖")
            return

        async with message.channel.typing():
            try:
                answer = await self._ask(message.channel.id, content, use_history=True)
            except ai.AIError:
                await message.reply(_error_msg())
                return

        chunks = _chunks(answer)
        await message.reply(chunks[0])
        for c in chunks[1:]:
            await message.channel.send(c)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Assistant(bot))

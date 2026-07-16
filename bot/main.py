"""봇 진입점: 인텐트 설정, Cog 로드, 슬래시 명령어 동기화."""
import asyncio
import logging

import discord
from discord.ext import commands

from bot import config, image_card
from bot.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


class MyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # 메시지 내용 인텐트 (개발자 포털에서도 켜야 함)
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # DB 초기화
        init_db()

        # 한글 폰트 준비 (없으면 여기서 받는다). 첫 전적 카드가 느려지지 않게
        # 미리 확보하고, 어떤 폰트를 쓰는지 로그로 남겨 깨짐을 바로 진단할 수 있게 한다.
        font_path = await asyncio.to_thread(image_card.font_status)
        log.info("전적 카드 폰트: %s", font_path)

        # Cog 로드
        for ext in config.INITIAL_COGS:
            await self.load_extension(ext)
            log.info("Loaded cog: %s", ext)

        # 슬래시 명령어 동기화
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, self.user.id)


async def main() -> None:
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요.")

    bot = MyBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

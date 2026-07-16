"""호스팅 실행용 런처: bot 패키지를 모듈로 실행한다.

FreeGameHost 등 'python <파일>' 방식으로 실행하는 호스트를 위해,
bot/main.py 의 main() 을 여기서 불러 실행한다.
"""
import asyncio

from bot.main import main

if __name__ == "__main__":
    asyncio.run(main())

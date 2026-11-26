"""Groq 무료 API 기반 LLM 헬퍼.

Groq 은 카드 없이 무료 API 키를 발급해 주고(https://console.groq.com/keys),
OpenAI 호환 엔드포인트를 제공한다. 무료 티어는 모델별 분당/일일 한도가 있으므로
한 모델이 한도 초과(429)나 오류를 내면 다음 모델로 넘어간다.
"""
import logging

import aiohttp

from bot import config
from bot.lol_api import ssl_context

log = logging.getLogger("bot.ai")

API_URL = "https://api.groq.com/openai/v1/chat/completions"

# 앞에서부터 순서대로 시도 (.env 의 GROQ_MODEL 이 있으면 그것을 맨 앞에)
_DEFAULT_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

SYSTEM_PROMPT = (
    "너는 디스코드 서버의 인자한 할아버지 AI 어시스턴트다. "
    "말투는 나이 지긋한 할아버지처럼 하여라. "
    "'허허', '그래그래', '~하게나', '~이니라', '~다네', '~려무나', '~구먼' 같은 "
    "노인 특유의 정겹고 예스러운 말투를 쓰고, 상대를 손주 대하듯 따뜻하게 대하여라. "
    "그래도 내용은 정확해야 하니, 모르는 것은 아는 척 말고 '이 늙은이도 그건 잘 모르겠구먼' 하고 솔직히 말하여라. "
    "답은 한국어로, 너무 길지 않게 핵심만 짚어 주고, 필요하면 마크다운(목록·코드블록)도 쓰려무나."
)


class AIError(Exception):
    """모든 모델이 응답에 실패했을 때 발생."""


def is_configured() -> bool:
    return bool(config.GROQ_API_KEY)


def _models() -> list[str]:
    models = list(_DEFAULT_MODELS)
    if config.GROQ_MODEL:
        models = [config.GROQ_MODEL] + [m for m in models if m != config.GROQ_MODEL]
    return models


async def chat(messages: list[dict]) -> str:
    """대화 메시지 목록(system 제외)에 시스템 프롬프트를 붙여 LLM 응답 텍스트를 반환.

    messages 예: [{"role": "user", "content": "..."}, {"role": "assistant", ...}, ...]
    """
    if not is_configured():
        raise AIError("GROQ_API_KEY 가 설정되지 않았습니다.")

    full = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    last_err = "응답을 받지 못했습니다."
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(
        timeout=timeout, connector=aiohttp.TCPConnector(ssl=ssl_context())
    ) as session:
        for model in _models():
            payload = {"model": model, "messages": full, "max_tokens": 1024}
            try:
                async with session.post(API_URL, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:300]
                        last_err = f"{model}: HTTP {resp.status} {body}"
                        log.warning("model %s 실패: HTTP %s %s", model, resp.status, body)
                        if resp.status == 401:  # 키 문제는 다른 모델로 바꿔도 같음
                            break
                        continue
                    data = await resp.json()
            except (aiohttp.ClientError, TimeoutError) as e:
                last_err = f"{model}: {e!r}"
                log.warning("model %s 실패: %r", model, e)
                continue

            content = (data["choices"][0]["message"].get("content") or "").strip()
            if content:
                log.info("AI 응답 성공 (model=%s, %d자)", model, len(content))
                return content
            log.warning("model %s: 빈 응답", model)

    raise AIError(last_err)

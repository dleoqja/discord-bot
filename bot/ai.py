"""gpt4free(g4f) 기반 무료 LLM 헬퍼 — API 키/로컬 모델 없이 동작한다.

무료 공개 엔드포인트를 경유하므로 특정 provider/model이 수시로 죽는다.
따라서 여러 모델을 순서대로 시도해 하나라도 성공하면 그 응답을 쓴다.
"""
import logging

from g4f.client import AsyncClient

log = logging.getLogger("bot.ai")

# 앞에서부터 순서대로 시도 (무료 provider가 자주 불안정하므로 폴백 체인)
_MODELS = ["gpt-4o-mini", "gpt-4o", "llama-3.3-70b", "gemini-1.5-flash"]

SYSTEM_PROMPT = (
    "너는 디스코드 서버의 인자한 할아버지 AI 어시스턴트다. "
    "말투는 나이 지긋한 할아버지처럼 하여라. "
    "'허허', '그래그래', '~하게나', '~이니라', '~다네', '~려무나', '~구먼' 같은 "
    "노인 특유의 정겹고 예스러운 말투를 쓰고, 상대를 손주 대하듯 따뜻하게 대하여라. "
    "그래도 내용은 정확해야 하니, 모르는 것은 아는 척 말고 '이 늙은이도 그건 잘 모르겠구먼' 하고 솔직히 말하여라. "
    "답은 한국어로, 너무 길지 않게 핵심만 짚어 주고, 필요하면 마크다운(목록·코드블록)도 쓰려무나."
)


class AIError(Exception):
    """모든 무료 모델이 응답에 실패했을 때 발생."""


async def chat(messages: list[dict]) -> str:
    """대화 메시지 목록(system 제외)에 시스템 프롬프트를 붙여 LLM 응답 텍스트를 반환.

    messages 예: [{"role": "user", "content": "..."}, {"role": "assistant", ...}, ...]
    """
    client = AsyncClient()
    full = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    last_err: Exception | None = None

    for model in _MODELS:
        try:
            resp = await client.chat.completions.create(model=model, messages=full)
            content = (resp.choices[0].message.content or "").strip()
            if content:
                log.info("AI 응답 성공 (model=%s, %d자)", model, len(content))
                return content
            log.warning("model %s: 빈 응답", model)
        except Exception as e:  # 무료 provider는 온갖 예외를 던진다
            last_err = e
            log.warning("model %s 실패: %s", model, e)

    raise AIError(str(last_err) if last_err else "응답을 받지 못했습니다.")

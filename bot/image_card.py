"""Pillow로 롤 전적 카드 이미지를 생성한다.

cog에서 데이터를 가공해 넘겨주면 PNG 바이트를 돌려준다.
줄마다 챔피언 얼굴을 원형으로 합성하는 것이 임베드로는 불가능한 부분.
"""
import io
import logging
import os
import ssl
import tempfile
import urllib.request
from functools import lru_cache

import certifi
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# 한글 폰트 (가변 폰트 — 굵기는 wght 축으로 조절).
# 동봉해서 올리는 게 정석이지만, 호스팅 패널 업로드가 누락/절단되는 일이 잦아
# 없으면 ddragon의 챔피언 이미지처럼 런타임에 받아서 캐싱한다.
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts"
)
_FONT_NAME = "NotoSansKR-VF.ttf"
_BUNDLED_FONT = os.path.join(_FONT_DIR, _FONT_NAME)
_FONT_URL = (
    "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
)
# 실제 폰트는 10MB대. 이보다 작으면 업로드가 잘린 것으로 보고 다시 받는다.
_MIN_FONT_BYTES = 1_000_000

# 동봉 폰트를 못 찾을 때 훑어볼 시스템 한글 폰트들 (리눅스 → 윈도우 순)
_SYSTEM_FONTS = {
    False: [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ],
}

# 색상 팔레트 (다크 테마)
BG = (24, 26, 32)
PANEL = (34, 37, 46)
TEXT = (235, 237, 242)
MUTED = (150, 156, 168)
ACCENT = (120, 170, 255)
WIN = (86, 152, 240)
LOSS = (232, 96, 96)

W = 760
PAD = 26
ROW_H = 60
FACE = 44
SECTION_GAP = 14


def _download_font(dest: str) -> str | None:
    """가변 폰트를 받아 dest에 저장하고 경로를 반환. 실패하면 None.

    dest 폴더가 쓰기 불가면(패널이 읽기 전용으로 마운트한 경우) 임시 폴더에 받는다.
    받다 끊긴 파일이 캐시로 남지 않게 임시 파일에 쓴 뒤 교체한다.
    """
    for target_dir in (os.path.dirname(dest), tempfile.gettempdir()):
        try:
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, _FONT_NAME)
            log.info("한글 폰트가 없어 받아온다: %s -> %s", _FONT_URL, path)
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(_FONT_URL, timeout=60, context=ctx) as resp:
                data = resp.read()
            if len(data) < _MIN_FONT_BYTES:
                log.warning("받은 폰트가 너무 작다(%d바이트) — 버린다.", len(data))
                return None
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            log.info("폰트 다운로드 완료: %s (%.1fMB)", path, len(data) / 1024 / 1024)
            return path
        except OSError as e:
            log.warning("폰트 다운로드/저장 실패 (%s): %s", target_dir, e)
            continue
    return None


@lru_cache(maxsize=1)
def _font_file() -> str | None:
    """쓸 수 있는 가변 폰트 파일 경로. 없으면 받아온다. 프로세스당 1회만 수행."""
    for path in (_BUNDLED_FONT, os.path.join(tempfile.gettempdir(), _FONT_NAME)):
        # 업로드가 잘려 0바이트로 남은 파일을 정상으로 오인하지 않도록 크기까지 본다
        if os.path.exists(path) and os.path.getsize(path) >= _MIN_FONT_BYTES:
            return path
    return _download_font(_BUNDLED_FONT)


@lru_cache(maxsize=None)
def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """한글 폰트를 연다.

    동봉 폰트 → 시스템 한글 폰트 → 다운로드 순으로 찾는다. 폴백인
    load_default()는 한글 글리프가 없어 글씨가 깨지므로 거기까지 내려가면 경고한다.
    """
    path = _font_file()
    if path:
        try:
            font = ImageFont.truetype(path, size)
            try:
                font.set_variation_by_name("Bold" if bold else "Regular")
            except OSError:
                # FreeType이 가변 폰트를 지원 안 하면 기본 굵기로 쓴다
                pass
            return font
        except OSError as e:
            log.warning("폰트 %s 를 여는 데 실패: %s", path, e)

    for sys_path in _SYSTEM_FONTS[bold]:
        try:
            return ImageFont.truetype(sys_path, size)
        except OSError:
            continue

    log.warning(
        "한글 폰트를 못 찾아 기본 폰트로 폴백한다 — 카드 글씨가 깨진다. "
        "%s 확인 필요.",
        _BUNDLED_FONT,
    )
    return ImageFont.load_default()


def font_status() -> str:
    """쓸 폰트를 미리 확보하고 사람이 읽을 설명을 돌려준다 (기동 로그용).

    첫 전적 카드에서 다운로드가 일어나지 않게 하고, 글씨가 깨질 상황이면
    사용자가 카드를 뽑아보기 전에 로그로 먼저 드러나게 한다.
    """
    font = _font(20)
    path = _font_file()
    if path:
        return path
    if isinstance(font, ImageFont.FreeTypeFont):
        return f"시스템 폰트 {font.path}"
    return "기본 폰트 — 한글이 깨진다! 네트워크와 assets/fonts 확인 필요"


def _circle_face(path: str | None, size: int) -> Image.Image:
    """이미지를 원형으로 크롭. 경로가 없으면 회색 원 플레이스홀더."""
    if path:
        try:
            src = Image.open(path).convert("RGBA").resize((size, size))
        except OSError:
            src = None
    else:
        src = None
    if src is None:
        src = Image.new("RGBA", (size, size), (70, 74, 84, 255))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render_card(header: dict, sections: list[dict]) -> bytes:
    """전적 카드 PNG 바이트를 생성한다.

    header: {name, level, rank_line, sub_line}
    sections: [{title, rows: [{img, name, right, sub, result}]}]
    """
    # 전체 높이 계산
    header_h = 118
    total_h = PAD + header_h
    for sec in sections:
        total_h += 46 + len(sec["rows"]) * ROW_H + SECTION_GAP
    total_h += PAD

    img = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(34, bold=True)
    f_rank = _font(21, bold=True)
    f_sub = _font(16)
    f_sec = _font(20, bold=True)
    f_name = _font(20, bold=True)
    f_right = _font(19, bold=True)
    f_small = _font(15)

    # ── 헤더 ──
    _rounded(draw, (PAD, PAD, W - PAD, PAD + header_h - 12), 16, PANEL)
    hx, hy = PAD + 24, PAD + 20
    draw.text((hx, hy), header["name"], font=f_title, fill=TEXT)
    draw.text((hx, hy + 44), f"Lv. {header['level']}", font=f_sub, fill=MUTED)
    # 랭크는 오른쪽 정렬
    rank_line = header.get("rank_line", "언랭")
    rw = draw.textlength(rank_line, font=f_rank)
    draw.text((W - PAD - 24 - rw, hy + 6), rank_line, font=f_rank, fill=ACCENT)
    sub_line = header.get("sub_line", "")
    if sub_line:
        sw = draw.textlength(sub_line, font=f_sub)
        draw.text((W - PAD - 24 - sw, hy + 40), sub_line, font=f_sub, fill=MUTED)

    y = PAD + header_h

    # ── 섹션들 ──
    for sec in sections:
        # 섹션 제목 + 구분선
        draw.text((PAD + 4, y + 10), sec["title"], font=f_sec, fill=(190, 198, 214))
        draw.line((PAD + 4, y + 40, W - PAD, y + 40), fill=(52, 56, 66), width=2)
        y += 46

        for row in sec["rows"]:
            result = row.get("result")
            # 승/패 왼쪽 컬러바
            if result:
                color = WIN if result == "win" else LOSS
                _rounded(draw, (PAD, y + 8, PAD + 5, y + ROW_H - 8), 3, color)

            # 챔프 얼굴 (face=False면 생략 — 라인별/평균 지표 등)
            if row.get("face", True):
                face = _circle_face(row.get("img"), FACE)
                img.paste(face, (PAD + 16, y + (ROW_H - FACE) // 2), face)
                tx = PAD + 16 + FACE + 16
            else:
                tx = PAD + 22
            draw.text((tx, y + 12), row["name"], font=f_name, fill=TEXT)
            if row.get("sub"):
                draw.text((tx, y + 36), row["sub"], font=f_small, fill=MUTED)

            # 오른쪽 스탯
            right = row.get("right", "")
            rcolor = TEXT
            if result:
                rcolor = WIN if result == "win" else LOSS
            rw = draw.textlength(right, font=f_right)
            draw.text((W - PAD - 20 - rw, y + 20), right, font=f_right, fill=rcolor)

            y += ROW_H
        y += SECTION_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

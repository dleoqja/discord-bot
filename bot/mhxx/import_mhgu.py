"""MHGU(= 해외판 MHXX) 실데이터 임포터.

Gathering Hall Studios 의 MHGenDatabase 에서 배포하는 SQLite DB(mhgu.db)를
읽어 방어구 세트 빌더용 JSON(bot/data/mhxx_data.json)으로 변환한다.

사용법:
    # DB가 없으면 자동 다운로드 후 변환
    python -m bot.mhxx.import_mhgu

    # 이미 받은 DB를 지정
    python -m bot.mhxx.import_mhgu --db path/to/mhgu.db

데이터 출처: https://github.com/gatheringhallstudios/MHGenDatabase
라이선스/출처 표기는 해당 저장소를 따른다.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import urllib.request
import zipfile

DB_URL = (
    "https://raw.githubusercontent.com/gatheringhallstudios/MHGenDatabase/"
    "master/app/src/main/assets/databases/mhgu.db.zip"
)

_HERE = os.path.dirname(__file__)
DEFAULT_DB = os.path.join(_HERE, "_mhgu.db")
OUT_PATH = os.path.join(os.path.dirname(_HERE), "data", "mhxx_data.json")

SLOT_TO_PART = {"Head": "head", "Body": "body", "Arms": "arms", "Waist": "waist", "Legs": "legs"}

# 자신 있는 주요 스킬트리만 한글 병기(나머지는 영어명 그대로 노출).
# GHStudios 영문 트리명(slug) -> 한글
KO_OVERRIDES = {
    "attack": "공격",
    "expert": "간파(견피)",
    "tenderizer": "약점특효",
    "criticalup": "초회심",
    "handicraft": "장인",
    "fastcharge": "집중",
    "constitution": "체술",
    "evasion": "회피성능",
    "guard": "가드성능",
    "health": "체력증강",
    "hearing": "청각보호",
    "reclevel": "회복속도",
    "windproof": "내풍압",
    "sharpness": "업물",
    "razorsharp": "업물",
    "artillery": "포술",
    "destroyer": "파괴왕",
    "capturer": "포획의명수",
    "biology": "생물학",
    "protection": "가호",
    "loadup": "장전수UP",
    "reloadspeed": "장전속도",
    "recoil": "반동",
    "status": "상태이상공격",
    "poison": "독",
    "paralysis": "마비",
    "sleep": "수면",
    "stun": "기절",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def download_db(dest: str) -> None:
    print(f"[*] mhgu.db.zip 다운로드 중... ({DB_URL})")
    with urllib.request.urlopen(DB_URL, timeout=180) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        inner = next(n for n in zf.namelist() if n.endswith(".db"))
        data = zf.read(inner)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"[*] 저장: {dest} ({len(data)//1024//1024}MB)")


def build(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # --- 스킬트리 + 고유 tree_id(slug) 매핑 (충돌 시 id 접미사) ---
    tree_id_by_dbid: dict[int, str] = {}
    used_slugs: set[str] = set()
    trees: dict[str, dict] = {}
    for r in con.execute("SELECT _id, name FROM skill_trees WHERE name != ''"):
        slug = _slugify(r["name"]) or f"tree{r['_id']}"
        if slug in used_slugs:
            slug = f"{slug}{r['_id']}"
        used_slugs.add(slug)
        tree_id_by_dbid[r["_id"]] = slug
        trees[slug] = {
            "en": r["name"],
            "ko": KO_OVERRIDES.get(slug),
            "activations": [],
        }

    # --- 발동 스킬(양수 포인트) = activations ---
    for r in con.execute(
        "SELECT skill_tree_id, required_skill_tree_points AS pts, name "
        "FROM skills WHERE required_skill_tree_points > 0 AND name != ''"
    ):
        slug = tree_id_by_dbid.get(r["skill_tree_id"])
        if slug:
            trees[slug]["activations"].append({"points": r["pts"], "name": r["name"]})
    for t in trees.values():
        t["activations"].sort(key=lambda a: a["points"], reverse=True)

    # 발동 스킬이 하나도 없는 트리는 제거(장식/방어구 계산엔 남겨도 무의미)
    trees = {k: v for k, v in trees.items() if v["activations"]}

    # --- item_id -> {tree_slug: points} 사전 ---
    skills_by_item: dict[int, dict[str, int]] = {}
    for r in con.execute("SELECT item_id, skill_tree_id, point_value FROM item_to_skill_tree"):
        slug = tree_id_by_dbid.get(r["skill_tree_id"])
        if not slug:
            continue
        skills_by_item.setdefault(r["item_id"], {})[slug] = r["point_value"]

    # --- 방어구 ---
    armor = []
    for r in con.execute(
        "SELECT a._id AS id, i.name AS name, a.slot, a.defense, a.max_defense, "
        "a.num_slots, a.gender, a.hunter_type, i.rarity "
        "FROM armor a JOIN items i ON a._id = i._id"
    ):
        part = SLOT_TO_PART.get(r["slot"])
        if not part:
            continue
        skills = skills_by_item.get(r["id"], {})
        armor.append({
            "id": r["id"],
            "part": part,
            "name": r["name"],
            "defense": max(r["max_defense"] or 0, r["defense"] or 0),
            "slots": r["num_slots"] or 0,
            "gender": r["gender"],           # 0/1 = 남/여, 2 = 공용
            "hunter_type": r["hunter_type"],  # 0 = 검사, 1 = 거너, 2 = 공용
            "rarity": r["rarity"] or 0,
            "skills": skills,
        })

    # --- 장식주(데코) ---
    decorations = []
    for r in con.execute(
        "SELECT d._id AS id, i.name AS name, d.num_slots "
        "FROM decorations d JOIN items i ON d._id = i._id"
    ):
        skills = skills_by_item.get(r["id"], {})
        if not skills:
            continue
        decorations.append({
            "id": r["id"],
            "name": r["name"],
            "slots": r["num_slots"],
            "skills": skills,
        })

    con.close()
    return {
        "_meta": {
            "source": "gatheringhallstudios/MHGenDatabase (mhgu.db)",
            "url": "https://github.com/gatheringhallstudios/MHGenDatabase",
            "note": "MHGU(= 해외판 몬스터헌터 더블크로스/MHXX) 실데이터. 스킬명은 영문이며 주요 트리만 한글 병기.",
            "counts": {"skill_trees": len(trees), "armor": len(armor), "decorations": len(decorations)},
        },
        "skill_trees": trees,
        "decorations": decorations,
        "armor": armor,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="mhgu.db 경로 (없으면 다운로드)")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    db_path = args.db or DEFAULT_DB
    if not os.path.exists(db_path):
        download_db(db_path)

    data = build(db_path)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    m = data["_meta"]["counts"]
    print(f"[+] 저장: {args.out}")
    print(f"    스킬트리 {m['skill_trees']} · 방어구 {m['armor']} · 장식주 {m['decorations']}")


if __name__ == "__main__":
    main()

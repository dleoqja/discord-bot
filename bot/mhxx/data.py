"""MHXX(= MHGU) 방어구/스킬 데이터 로딩 및 조회.

data/mhxx_data.json 을 읽어 파이썬 dataclass 로 변환한다. 이 JSON 은
bot.mhxx.import_mhgu 로 실제 MHGU DB 에서 생성된다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mhxx_data.json")

PARTS = ("head", "body", "arms", "waist", "legs")
PART_KO = {"head": "머리", "body": "몸통", "arms": "팔", "waist": "허리", "legs": "다리"}

# hunter_type / gender 인코딩 (import_mhgu.py 참고)
HT_BLADEMASTER, HT_GUNNER, HT_BOTH = 0, 1, 2
GENDER_MALE, GENDER_FEMALE, GENDER_BOTH = 0, 1, 2


@dataclass(frozen=True)
class Activation:
    points: int
    name: str


@dataclass(frozen=True)
class SkillTree:
    tree_id: str
    en: str
    ko: str | None
    activations: tuple[Activation, ...]  # 포인트 내림차순

    @property
    def label(self) -> str:
        return f"{self.ko} ({self.en})" if self.ko else self.en


@dataclass(frozen=True)
class Decoration:
    id: int
    name: str
    slots: int
    skills: dict[str, int]  # tree_id -> 포인트(음수=패널티)


@dataclass(frozen=True)
class ArmorPiece:
    id: int
    part: str
    name: str
    defense: int
    slots: int
    gender: int
    hunter_type: int
    rarity: int
    skills: dict[str, int] = field(default_factory=dict)

    def fits(self, hunter_type: int | None, gender: int | None) -> bool:
        if hunter_type is not None and self.hunter_type != HT_BOTH and self.hunter_type != hunter_type:
            return False
        if gender is not None and self.gender != GENDER_BOTH and self.gender != gender:
            return False
        return True


@dataclass
class GameData:
    trees: dict[str, SkillTree]
    armor_by_part: dict[str, list[ArmorPiece]]
    decorations: list[Decoration]

    def tree_label(self, tree_id: str) -> str:
        t = self.trees.get(tree_id)
        return t.label if t else tree_id

    def tree_ko(self, tree_id: str) -> str:
        t = self.trees.get(tree_id)
        if not t:
            return tree_id
        return t.ko or t.en

    def activation_name(self, tree_id: str, points: int) -> str | None:
        tree = self.trees.get(tree_id)
        if not tree:
            return None
        for act in tree.activations:  # 내림차순
            if points >= act.points:
                return act.name
        return None

    def decos_for_tree(self, tree_id: str) -> list[Decoration]:
        """해당 트리에 양수 포인트를 주는 장식주를, 슬롯당 효율 좋은 순으로."""
        cands = [d for d in self.decorations if d.skills.get(tree_id, 0) > 0]
        cands.sort(key=lambda d: (d.skills[tree_id] / d.slots, -d.slots), reverse=True)
        return cands


def _load() -> GameData:
    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    trees: dict[str, SkillTree] = {}
    for tree_id, t in raw["skill_trees"].items():
        acts = tuple(
            Activation(a["points"], a["name"])
            for a in sorted(t["activations"], key=lambda a: a["points"], reverse=True)
        )
        trees[tree_id] = SkillTree(tree_id=tree_id, en=t["en"], ko=t.get("ko"), activations=acts)

    armor_by_part: dict[str, list[ArmorPiece]] = {p: [] for p in PARTS}
    for a in raw["armor"]:
        piece = ArmorPiece(
            id=a["id"], part=a["part"], name=a["name"],
            defense=a.get("defense", 0), slots=a.get("slots", 0),
            gender=a.get("gender", GENDER_BOTH), hunter_type=a.get("hunter_type", HT_BOTH),
            rarity=a.get("rarity", 0),
            skills={k: int(v) for k, v in a.get("skills", {}).items()},
        )
        armor_by_part.setdefault(piece.part, []).append(piece)

    decorations = [
        Decoration(id=d["id"], name=d["name"], slots=d["slots"],
                   skills={k: int(v) for k, v in d["skills"].items()})
        for d in raw["decorations"]
    ]

    return GameData(trees=trees, armor_by_part=armor_by_part, decorations=decorations)


@lru_cache(maxsize=1)
def get_data() -> GameData:
    return _load()


def reload_data() -> GameData:
    get_data.cache_clear()
    return get_data()

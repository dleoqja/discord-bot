"""방어구 세트 탐색기 (실데이터 5000+ 방어구 대응).

동작 개요:
  1) 무기타입(검사/거너)·성별로 방어구를 필터링한다.
  2) 부위별 후보 = [목표 스킬 포인트+슬롯 기준 Pareto 우세 방어구]
                 ∪ [스킬 포인트 총합이 높은 방어구 상위 N개(보너스용)].
  3) 5부위를 분기한정(branch & bound) DFS 로 탐색해, 요청 스킬을 만족하는
     '기본 세트'를 모은다(요청 스킬은 반드시 발동).
  4) 상위 후보에 대해, 남는 슬롯 + 호석 슬롯을 장식주로 채워 '보너스 스킬'을
     최대한 추가로 발동시키고, 발동 스킬 수가 많은 순으로 6개를 고른다.
"""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field

from bot.mhxx.data import ArmorPiece, Decoration, GameData, PARTS

_MAX_NODES = 3_000_000
_MAX_LEAVES = 60_000
_KEEP_FOR_BONUS = 400   # 2단계(보너스 최적화)로 넘길 상위 후보 수
_TOPN_BONUS_PIECES = 10  # 부위별로 추가 보존할 '포인트 많은' 방어구 수
_DECO_PASSES = 60


@dataclass(frozen=True)
class Target:
    tree_id: str
    required_points: int


@dataclass(frozen=True)
class Charm:
    skills: dict[str, int] = field(default_factory=dict)
    slots: int = 0


@dataclass
class SetResult:
    pieces: dict[str, ArmorPiece]
    decorations: list[tuple[Decoration, int]]
    total_defense: int
    used_slots: int
    total_slots: int
    # (트리 라벨, 발동 스킬명, 요청 스킬 여부)
    activations: list[tuple[str, str, bool]]

    @property
    def leftover_slots(self) -> int:
        return self.total_slots - self.used_slots

    @property
    def skill_count(self) -> int:
        return len(self.activations)


def _pos_points(piece: ArmorPiece) -> int:
    return sum(v for v in piece.skills.values() if v > 0)


# ---------------------------------------------------------------- 장식주(목표)
def _fill_targets(
    base_points: dict[str, int],
    targets: list[Target],
    free_slots: int,
    deco_cache: dict[str, list[Decoration]],
) -> tuple[list[tuple[Decoration, int]], int] | None:
    """요청 스킬 부족분을 장식주로 채운다. 성공 시 ([(deco,cnt)], 남은슬롯)."""
    pts = dict(base_points)
    used: dict[int, tuple[Decoration, int]] = {}
    for _ in range(_DECO_PASSES):
        unmet = [t for t in targets if pts.get(t.tree_id, 0) < t.required_points]
        if not unmet:
            return list(used.values()), free_slots
        progressed = False
        for t in unmet:
            deficit = t.required_points - pts.get(t.tree_id, 0)
            deco = next((d for d in deco_cache[t.tree_id] if d.slots <= free_slots), None)
            if deco is None:
                continue
            cnt = min(math.ceil(deficit / deco.skills[t.tree_id]), free_slots // deco.slots)
            if cnt <= 0:
                continue
            free_slots -= cnt * deco.slots
            prev = used.get(deco.id)
            used[deco.id] = (deco, (prev[1] if prev else 0) + cnt)
            for tid, val in deco.skills.items():
                pts[tid] = pts.get(tid, 0) + val * cnt
            progressed = True
        if not progressed:
            return None
    return None


# ---------------------------------------------------------------- 장식주(보너스)
def _fill_bonus(
    data: GameData,
    points: dict[str, int],
    free_slots: int,
    target_ids: set[str],
    bonus_decos: dict[str, list[Decoration]],
    asc_thresholds: dict[str, list[int]],
    popularity: dict[str, int],
) -> tuple[list[tuple[Decoration, int]], dict[str, int]]:
    """남는 슬롯으로 '새 스킬'을 최대한 발동시킨다.

    선택 우선순위: 슬롯 비용이 적은 것 → 같은 비용이면 더 대중적인 스킬.
    """
    pts = dict(points)
    used: dict[int, tuple[Decoration, int]] = {}

    while free_slots > 0:
        best = None       # (tid, deco, cnt)
        best_key = None    # (cost, -popularity)
        for tid, thresholds in asc_thresholds.items():
            cur = pts.get(tid, 0)
            nxt = next((p for p in thresholds if p > cur), None)
            if nxt is None:
                continue
            need = nxt - cur
            deco = next((d for d in bonus_decos.get(tid, ()) if d.slots <= free_slots), None)
            if deco is None:
                continue
            cnt = math.ceil(need / deco.skills[tid])
            cost = cnt * deco.slots
            if cost > free_slots:
                continue
            key = (cost, -popularity.get(tid, 0))
            if best_key is None or key < best_key:
                best_key, best = key, (tid, deco, cnt)
        if best is None:
            break
        tid, deco, cnt = best
        cost = cnt * deco.slots
        free_slots -= cost
        prev = used.get(deco.id)
        used[deco.id] = (deco, (prev[1] if prev else 0) + cnt)
        for t2, val in deco.skills.items():
            pts[t2] = pts.get(t2, 0) + val * cnt
    return list(used.values()), pts


def _collect_activations(
    data: GameData, points: dict[str, int], target_ids: set[str]
) -> list[tuple[str, str, bool]]:
    acts: list[tuple[str, str, bool]] = []
    ordered = list(target_ids) + [k for k in points if k not in target_ids]
    for tid in ordered:
        name = data.activation_name(tid, points.get(tid, 0))
        if name:
            acts.append((data.tree_label(tid), name, tid in target_ids))
    # 요청 스킬 먼저, 그다음 보너스
    acts.sort(key=lambda a: (not a[2],))
    return acts


# ---------------------------------------------------------------- Pareto 축소
def _pareto_reduce(pieces: list[ArmorPiece], target_ids: list[str]) -> list[ArmorPiece]:
    best: dict[tuple, ArmorPiece] = {}
    for p in pieces:
        key = tuple(p.skills.get(t, 0) for t in target_ids) + (p.slots,)
        cur = best.get(key)
        if cur is None or _pos_points(p) > _pos_points(cur):
            best[key] = p
    items = list(best.items())
    keep: list[ArmorPiece] = []
    for i, (ki, pi) in enumerate(items):
        if not any(
            i != j and all(b >= a for a, b in zip(ki, kj)) and any(b > a for a, b in zip(ki, kj))
            for j, (kj, _pj) in enumerate(items)
        ):
            keep.append(pi)
    return keep


def _candidates(part_pieces: list[ArmorPiece], target_ids: list[str]) -> list[ArmorPiece]:
    """Pareto 후보 + 스킬 포인트 많은 상위 N개(보너스용)를 합침."""
    frontier = _pareto_reduce(part_pieces, target_ids)
    bonus = sorted(part_pieces, key=_pos_points, reverse=True)[:_TOPN_BONUS_PIECES]
    seen = {id(p) for p in frontier}
    for p in bonus:
        if id(p) not in seen:
            frontier.append(p)
            seen.add(id(p))
    return frontier


# ---------------------------------------------------------------- 메인 탐색
def solve(
    data: GameData,
    targets: list[Target],
    hunter_type: int | None = None,
    gender: int | None = None,
    charm: Charm | None = None,
    max_results: int = 6,
) -> list[SetResult]:
    if not targets:
        return []
    charm = charm or Charm()
    target_ids_list = [t.tree_id for t in targets]
    target_ids = set(target_ids_list)

    # 장식주 사전
    deco_cache = {t.tree_id: data.decos_for_tree(t.tree_id) for t in targets}
    best_pps = {t.tree_id: max((d.skills[t.tree_id] / d.slots for d in deco_cache[t.tree_id]),
                               default=0.0) for t in targets}

    # 보너스용 전 트리 장식주/임계값 사전
    bonus_decos: dict[str, list[Decoration]] = {}
    for d in data.decorations:
        for tid, val in d.skills.items():
            if val > 0 and tid not in target_ids:
                bonus_decos.setdefault(tid, []).append(d)
    for tid in bonus_decos:
        bonus_decos[tid].sort(key=lambda d: (d.skills[tid] / d.slots, -d.slots), reverse=True)
        # 목표 스킬을 깎는 패널티가 있는 장식주는 보너스용에서 제외(요청 스킬 보호)
        bonus_decos[tid] = [d for d in bonus_decos[tid]
                            if not any(v < 0 and k in target_ids for k, v in d.skills.items())]
    asc_thresholds = {
        tid: sorted(a.points for a in tree.activations if a.points > 0)
        for tid, tree in data.trees.items() if tid in bonus_decos
    }
    # 대중도 = 해당 트리에 양수 포인트를 주는 방어구 수 (보너스 스킬 선택 보정용)
    popularity: dict[str, int] = {}
    for part in PARTS:
        for piece in data.armor_by_part.get(part, []):
            for tid, val in piece.skills.items():
                if val > 0:
                    popularity[tid] = popularity.get(tid, 0) + 1

    # 요청 스킬을 방어구/장식 어디서도 못 얻으면 불가
    for t in targets:
        if not deco_cache[t.tree_id] and not any(
            p.skills.get(t.tree_id, 0) > 0
            for part in PARTS for p in data.armor_by_part.get(part, [])
        ):
            return []

    # 부위별 후보
    frontiers: list[list[ArmorPiece]] = []
    for part in PARTS:
        fitting = [p for p in data.armor_by_part.get(part, []) if p.fits(hunter_type, gender)]
        if not fitting:
            return []
        frontiers.append(_candidates(fitting, target_ids_list))

    n = len(PARTS)
    suf_pts = [dict.fromkeys(target_ids_list, 0) for _ in range(n + 1)]
    suf_slot = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        fr = frontiers[i]
        suf_slot[i] = suf_slot[i + 1] + max(p.slots for p in fr)
        for tid in target_ids_list:
            suf_pts[i][tid] = suf_pts[i + 1][tid] + max(p.skills.get(tid, 0) for p in fr)

    # 1단계: 요청 스킬을 만족하는 후보를 proxy 점수 상위 _KEEP_FOR_BONUS개만 보관
    heap: list[tuple[float, int]] = []          # (proxy, uid) 최소힙
    store: dict[int, tuple] = {}                 # uid -> (pieces, target_decos, leftover, tgt_points)
    counter = itertools.count()
    seen: set[tuple[int, ...]] = set()
    stats = {"nodes": 0, "leaves": 0}

    def consider(chosen: list[ArmorPiece], tgt_points: dict[str, int], slots: int) -> None:
        filled = _fill_targets(tgt_points, targets, slots, deco_cache)
        if filled is None:
            return
        target_decos, leftover = filled
        key = tuple(sorted(p.id for p in chosen))
        if key in seen:
            return
        seen.add(key)
        proxy = leftover * 3 + sum(_pos_points(p) for p in chosen) + sum(p.defense for p in chosen) * 0.001
        uid = next(counter)
        if len(heap) < _KEEP_FOR_BONUS:
            heapq.heappush(heap, (proxy, uid))
            store[uid] = (list(chosen), target_decos, leftover, dict(tgt_points))
        elif proxy > heap[0][0]:
            _, old = heapq.heappushpop(heap, (proxy, uid))
            store.pop(old, None)
            store[uid] = (list(chosen), target_decos, leftover, dict(tgt_points))

    def dfs(depth: int, chosen: list[ArmorPiece], points: dict[str, int], slots: int) -> None:
        if stats["nodes"] > _MAX_NODES or stats["leaves"] > _MAX_LEAVES:
            return
        stats["nodes"] += 1
        opt_slots = slots + suf_slot[depth]
        for t in targets:
            upper = points.get(t.tree_id, 0) + suf_pts[depth][t.tree_id] + best_pps[t.tree_id] * opt_slots
            if upper < t.required_points:
                return
        if depth == n:
            stats["leaves"] += 1
            consider(chosen, points, slots)
            return
        for piece in frontiers[depth]:
            new_points = dict(points)
            for tid, val in piece.skills.items():
                if tid in target_ids:
                    new_points[tid] = new_points.get(tid, 0) + val
            dfs(depth + 1, chosen + [piece], new_points, slots + piece.slots)

    start = {tid: charm.skills.get(tid, 0) for tid in target_ids_list}
    dfs(0, [], start, charm.slots)

    # 2단계: 보관된 후보에 보너스 스킬 최대화 + 정확 채점
    results: list[SetResult] = []
    for _, uid in heap:
        chosen, target_decos, leftover, _tp = store[uid]
        # 세트의 전체 스킬 포인트(모든 트리) = 방어구 + 호석 + 목표장식
        full: dict[str, int] = dict(charm.skills)
        for p in chosen:
            for tid, val in p.skills.items():
                full[tid] = full.get(tid, 0) + val
        used: dict[int, tuple[Decoration, int]] = {d.id: (d, c) for d, c in target_decos}
        for d, c in target_decos:
            for tid, val in d.skills.items():
                full[tid] = full.get(tid, 0) + val * c

        bonus_used, final_points = _fill_bonus(
            data, full, leftover, target_ids, bonus_decos, asc_thresholds, popularity
        )
        for d, c in bonus_used:
            prev = used.get(d.id)
            used[d.id] = (d, (prev[1] if prev else 0) + c)

        total_slots = sum(p.slots for p in chosen) + charm.slots
        used_slots = sum(d.slots * c for d, c in used.values())
        results.append(SetResult(
            pieces={p.part: p for p in chosen},
            decorations=list(used.values()),
            total_defense=sum(p.defense for p in chosen),
            used_slots=used_slots,
            total_slots=total_slots,
            activations=_collect_activations(data, final_points, target_ids),
        ))

    # 발동 스킬 많은 순 → 방어력 높은 순
    results.sort(key=lambda r: (r.skill_count, r.total_defense), reverse=True)
    return results[:max_results]

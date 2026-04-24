"""Map-aware placement sampler.

Arma missions come alive when units stand on the actual terrain features of
the map — towns, airfields, roads. We ship small hand-curated `data/maps/*.json`
files with points-of-interest and road polylines so the generator can pick
real-world locations instead of the (100, 100, 0) hard-coded dump that
early iterations used.

The sampler is deterministic: callers pass a `seed` so the same brief
regenerates to the same layout unless the designer explicitly rerolls.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from ..config import data_dir


@dataclass
class PointOfInterest:
    id: str
    kind: str              # urban | airfield | hill | outpost | industrial
    position: tuple[float, float, float]
    radius: float = 200.0


@dataclass
class MapData:
    world: str
    size: tuple[float, float]
    points_of_interest: list[PointOfInterest]
    roads: list[list[tuple[float, float]]]
    lz_candidates: list[tuple[str, tuple[float, float, float]]]


_CACHE: dict[str, MapData] = {}


def load_map(world: str) -> MapData | None:
    """Return ``MapData`` for ``world`` (e.g. 'Tanoa') or None if unknown.

    Unknown worlds are tolerated: callers fall back to the legacy synthetic
    (100, 100, 0) placement so missions still generate. The QA layer flags
    the absence via an INFO finding so designers know they're missing
    map-aware placement.
    """
    if world in _CACHE:
        return _CACHE[world]
    path = data_dir() / "maps" / f"{world}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    pois = [
        PointOfInterest(
            id=p["id"], kind=p["kind"],
            position=tuple(p["position"]),
            radius=float(p.get("radius", 200.0)),
        )
        for p in raw.get("points_of_interest", [])
    ]
    roads = [
        [tuple(pt) for pt in line] for line in raw.get("roads", [])
    ]
    lzs = [
        (lz["id"], tuple(lz["position"]))
        for lz in raw.get("lz_candidates", [])
    ]
    md = MapData(
        world=world,
        size=tuple(raw.get("size", [10240, 10240])),
        points_of_interest=pois,
        roads=roads,
        lz_candidates=lzs,
    )
    _CACHE[world] = md
    return md


class MapSampler:
    """Deterministic picker over the curated map data."""

    def __init__(self, world: str, *, seed: int = 42) -> None:
        self.world = world
        self.data = load_map(world)
        self.rng = random.Random(seed)

    @property
    def available(self) -> bool:
        return self.data is not None

    def poi_by_kind(self, kind: str) -> list[PointOfInterest]:
        if not self.data:
            return []
        return [p for p in self.data.points_of_interest if p.kind == kind]

    def pick_poi(self, *, kind: str | None = None) -> PointOfInterest | None:
        if not self.data:
            return None
        candidates = (
            self.poi_by_kind(kind) if kind else list(self.data.points_of_interest)
        )
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def urban_cover_near(
        self,
        anchor: tuple[float, float, float] | None = None,
        *,
        radius: float = 400.0,
    ) -> tuple[float, float, float]:
        """Return a point inside a nearby town (or anchor itself if none)."""
        if not self.data:
            return anchor or (0.0, 0.0, 0.0)
        if anchor is None:
            p = self.pick_poi(kind="urban") or self.pick_poi()
            if p is None:
                return (0.0, 0.0, 0.0)
            return self._jitter(p.position, p.radius)
        # Pick the closest urban POI to anchor and jitter within its radius.
        pois = self.poi_by_kind("urban") or self.data.points_of_interest
        if not pois:
            return anchor
        closest = min(pois, key=lambda p: _dist(p.position, anchor))
        return self._jitter(closest.position, min(radius, closest.radius))

    def lz_near(
        self,
        anchor: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        """Return the closest curated LZ to ``anchor``."""
        if not self.data or not self.data.lz_candidates:
            return anchor
        _id, pos = min(
            self.data.lz_candidates, key=lambda lz: _dist(lz[1], anchor)
        )
        return pos

    def road_patrol(
        self,
        count: int,
        *,
        anchor: tuple[float, float, float] | None = None,
    ) -> list[tuple[float, float, float]]:
        """Return ``count`` waypoints sampled along a road polyline.

        Prefers the road nearest the anchor. When the map has no road data
        we fall back to a circular patrol around the anchor so the
        caller's FSM still has concrete waypoints.
        """
        if not self.data or not self.data.roads:
            return self._circular_patrol(anchor or (0.0, 0.0, 0.0), count, 200.0)
        road = (
            min(
                self.data.roads,
                key=lambda line: _dist(_line_centre(line), anchor),
            )
            if anchor is not None
            else self.rng.choice(self.data.roads)
        )
        picks = [self._along_road(road, t)
                 for t in self._even_ts(count, len(road))]
        return picks

    # -------------------------------------------------------------- internal

    def _jitter(
        self, pos: tuple[float, float, float], radius: float
    ) -> tuple[float, float, float]:
        ang = self.rng.random() * math.tau
        r = self.rng.random() ** 0.5 * radius
        return (pos[0] + math.cos(ang) * r, pos[1] + math.sin(ang) * r, pos[2])

    def _circular_patrol(
        self,
        centre: tuple[float, float, float],
        count: int,
        radius: float,
    ) -> list[tuple[float, float, float]]:
        return [
            (centre[0] + math.cos(i * math.tau / count) * radius,
             centre[1] + math.sin(i * math.tau / count) * radius,
             centre[2])
            for i in range(max(1, count))
        ]

    @staticmethod
    def _even_ts(count: int, n_points: int) -> list[float]:
        if count <= 0 or n_points < 2:
            return [0.0] * max(1, count)
        step = (n_points - 1) / max(1, count - 1) if count > 1 else 0
        return [step * i for i in range(count)]

    @staticmethod
    def _along_road(
        road: list[tuple[float, float]], t: float,
    ) -> tuple[float, float, float]:
        seg = int(math.floor(t))
        frac = t - seg
        if seg >= len(road) - 1:
            return (road[-1][0], road[-1][1], 0.0)
        a, b = road[seg], road[seg + 1]
        return (a[0] + (b[0] - a[0]) * frac,
                a[1] + (b[1] - a[1]) * frac,
                0.0)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _line_centre(line: list[tuple[float, float]]) -> tuple[float, float, float]:
    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    return (sum(xs) / len(xs), sum(ys) / len(ys), 0.0)


def available_maps() -> list[str]:
    directory = data_dir() / "maps"
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))

"""World model: the virtual sheet of paper under the SmartMotor arm.

Co-authored-by: GPT-5, Aug 2026
"""

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class Patch:
    start: float
    end: float
    color: tuple[int, int, int]
    name: str = ""

    def contains(self, angle_deg):
        return self.start <= angle_deg < self.end

    def distance_to_edge(self, angle_deg):
        return min(abs(angle_deg - self.start), abs(self.end - angle_deg))

    def to_dict(self):
        return {
            "from": self.start,
            "to": self.end,
            "color": _hex(self.color),
            "name": self.name,
        }


class World:
    def __init__(self, *, ambient_lux=300, patches=None, default_color="#ffffff", blur_deg=3):
        self.ambient_lux = ambient_lux
        self.default_color = _rgb(default_color)
        self.blur_deg = blur_deg  # GUESS: sensor spot size; needs bench data.
        self.patches = [_patch(patch) for patch in (patches or [])]
        self._validate_no_overlaps()

    @classmethod
    def load(cls, path: str) -> "World":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data = data.get("world", data)
        return cls(
            ambient_lux=data.get("ambient_lux", 300),
            patches=data.get("patches", data.get("surface", [])),
            default_color=data.get("default_color", "#ffffff"),
            blur_deg=data.get("blur_deg", 3),
        )

    def patch_at(self, angle_deg: float) -> Patch | None:
        for patch in self.patches:
            if patch.contains(angle_deg):
                return patch
        return None

    def color_at(self, angle_deg: float) -> tuple[int, int, int]:
        patch = self.patch_at(angle_deg)
        base = patch.color if patch is not None else self.default_color
        if self.blur_deg <= 0:
            return base

        other, distance = self._nearest_other_color(angle_deg, patch)
        if other is None or distance >= self.blur_deg:
            return base
        amount_other = (self.blur_deg - distance) / (2 * self.blur_deg)
        return _mix(base, other, amount_other)

    def lux_at(self, angle_deg: float) -> float:
        r, g, b = self.color_at(angle_deg)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return self.ambient_lux * (luminance / 255)

    def to_dict(self) -> dict:
        return {
            "ambient_lux": self.ambient_lux,
            "default_color": _hex(self.default_color),
            "blur_deg": self.blur_deg,
            "patches": [patch.to_dict() for patch in self.patches],
        }

    def _nearest_other_color(self, angle_deg, current_patch):
        candidates = []
        if current_patch is not None:
            candidates.append((self.default_color, current_patch.distance_to_edge(angle_deg)))
        else:
            for patch in self.patches:
                if angle_deg < patch.start:
                    candidates.append((patch.color, patch.start - angle_deg))
                elif angle_deg >= patch.end:
                    candidates.append((patch.color, angle_deg - patch.end))
        if not candidates:
            return None, None
        return min(candidates, key=lambda candidate: candidate[1])

    def _validate_no_overlaps(self):
        sorted_patches = sorted(self.patches, key=lambda patch: patch.start)
        for left, right in zip(sorted_patches, sorted_patches[1:]):
            if left.end > right.start:
                raise ValueError(f"world patches overlap: {left.name!r} and {right.name!r}")


def _patch(data):
    return Patch(
        start=float(data["from"]),
        end=float(data["to"]),
        color=_rgb(data["color"]),
        name=data.get("name", ""),
    )


def _rgb(value):
    if isinstance(value, (list, tuple)):
        if len(value) != 3:
            raise ValueError("RGB colors need exactly three channels")
        return tuple(int(channel) for channel in value)
    value = value.removeprefix("#")
    if len(value) != 6:
        raise ValueError("hex colors must be #rrggbb")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _hex(color):
    return "#{:02x}{:02x}{:02x}".format(*color)


def _mix(base, other, amount_other):
    amount_base = 1 - amount_other
    return tuple(int(round(base[i] * amount_base + other[i] * amount_other)) for i in range(3))

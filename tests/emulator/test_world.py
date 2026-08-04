"""T016 world model tests.

Co-authored-by: GPT-5, Aug 2026
"""

import json

import pytest

from smotoremu.world import World


def test_color_at_inside_patch_returns_patch_color():
    world = World(
        patches=[
            {"from": 0, "to": 30, "color": "#e02020", "name": "red"},
        ],
        default_color="#ffffff",
    )

    assert world.color_at(10) == (224, 32, 32)
    assert world.patch_at(10).name == "red"


def test_color_at_gap_returns_default_color():
    world = World(
        patches=[
            {"from": 0, "to": 30, "color": "#e02020", "name": "red"},
        ],
        default_color="#ffffff",
    )

    assert world.patch_at(45) is None
    assert world.color_at(45) == (255, 255, 255)


def test_blurred_boundary_interpolates_monotonically():
    world = World(
        patches=[
            {"from": 0, "to": 30, "color": "#000000", "name": "black"},
        ],
        default_color="#ffffff",
        blur_deg=4,
    )

    near_inside = world.color_at(29)[0]
    at_edge = world.color_at(30)[0]
    near_outside = world.color_at(31)[0]

    assert near_inside < at_edge < near_outside


def test_overlapping_patches_raise_at_load(tmp_path):
    path = tmp_path / "world.json"
    path.write_text(
        json.dumps(
            {
                "ambient_lux": 300,
                "default_color": "#ffffff",
                "patches": [
                    {"from": 0, "to": 30, "color": "#000000", "name": "first"},
                    {"from": 20, "to": 40, "color": "#ffffff", "name": "second"},
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="overlap"):
        World.load(path)


def test_shipped_three_patches_world_loads():
    world = World.load("smotoremu/worlds/three_patches.json")

    assert world.color_at(10) == (224, 32, 32)
    assert world.color_at(35) == (240, 240, 240)
    assert world.color_at(60) == (32, 80, 224)
    assert world.ambient_lux == 300
    assert world.to_dict()["patches"][0]["name"] == "red patch"

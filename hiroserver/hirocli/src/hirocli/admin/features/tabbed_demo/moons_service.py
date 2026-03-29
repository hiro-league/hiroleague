"""Demo service: static moon data keyed by planet (no tool dependency, guidelines §1.3)."""

from __future__ import annotations

from hirocli.admin.shared.result import Result

MOONS: dict[str, list[dict]] = {
    "earth": [
        {"id": "moon", "name": "Moon", "diameter_km": 3475, "discovery": "Prehistoric"},
    ],
    "mars": [
        {"id": "phobos", "name": "Phobos", "diameter_km": 22, "discovery": "1877"},
        {"id": "deimos", "name": "Deimos", "diameter_km": 12, "discovery": "1877"},
    ],
    "jupiter": [
        {"id": "io", "name": "Io", "diameter_km": 3643, "discovery": "1610"},
        {"id": "europa", "name": "Europa", "diameter_km": 3122, "discovery": "1610"},
        {"id": "ganymede", "name": "Ganymede", "diameter_km": 5268, "discovery": "1610"},
        {"id": "callisto", "name": "Callisto", "diameter_km": 4821, "discovery": "1610"},
    ],
    "saturn": [
        {"id": "titan", "name": "Titan", "diameter_km": 5150, "discovery": "1655"},
        {"id": "enceladus", "name": "Enceladus", "diameter_km": 504, "discovery": "1789"},
        {"id": "mimas", "name": "Mimas", "diameter_km": 396, "discovery": "1789"},
    ],
    "uranus": [
        {"id": "titania", "name": "Titania", "diameter_km": 1578, "discovery": "1787"},
        {"id": "oberon", "name": "Oberon", "diameter_km": 1523, "discovery": "1787"},
    ],
    "neptune": [
        {"id": "triton", "name": "Triton", "diameter_km": 2707, "discovery": "1846"},
    ],
}


class MoonsService:
    """In a real feature this would wrap a tool call; here it returns static data."""

    def list(self, planet_id: str | None = None) -> Result[list[dict]]:
        try:
            if planet_id:
                data = MOONS.get(planet_id, [])
            else:
                data = [m for moons in MOONS.values() for m in moons]
            return Result.success(data)
        except Exception as e:
            return Result.fail(str(e))

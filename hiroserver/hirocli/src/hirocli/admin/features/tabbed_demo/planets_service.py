"""Demo service: static planet data (no tool dependency, guidelines §1.3)."""

from __future__ import annotations

from hirocli.admin.shared.result import Result

PLANETS = [
    {"id": "mercury", "name": "Mercury", "type": "Terrestrial", "moons": 0, "diameter_km": 4879},
    {"id": "venus", "name": "Venus", "type": "Terrestrial", "moons": 0, "diameter_km": 12104},
    {"id": "earth", "name": "Earth", "type": "Terrestrial", "moons": 1, "diameter_km": 12756},
    {"id": "mars", "name": "Mars", "type": "Terrestrial", "moons": 2, "diameter_km": 6792},
    {"id": "jupiter", "name": "Jupiter", "type": "Gas giant", "moons": 95, "diameter_km": 142984},
    {"id": "saturn", "name": "Saturn", "type": "Gas giant", "moons": 146, "diameter_km": 120536},
    {"id": "uranus", "name": "Uranus", "type": "Ice giant", "moons": 28, "diameter_km": 51118},
    {"id": "neptune", "name": "Neptune", "type": "Ice giant", "moons": 16, "diameter_km": 49528},
]


class PlanetsService:
    """In a real feature this would wrap a tool call; here it returns static data."""

    def list(self, planet_type: str | None = None) -> Result[list[dict]]:
        try:
            data = PLANETS
            if planet_type:
                data = [p for p in data if p["type"].lower() == planet_type.lower()]
            return Result.success(data)
        except Exception as e:
            return Result.fail(str(e))

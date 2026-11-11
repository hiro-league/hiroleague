"""Shapes several routers answer with. Each router declares its own input and output models next to its
routes; the frontend's types are generated from them (frontend/src/lib/api/generated.ts)."""

from pydantic import BaseModel, ConfigDict


class Ok(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # every answer has every field
    ok: bool = True

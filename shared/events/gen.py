from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from . import CLIENT_EVENTS, SERVER_EVENTS


def _schemas_for(
    events: dict[str, Any],
    ref_prefix: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, top = models_json_schema(
        [(cls, "validation") for cls in events.values()],
        ref_template=f"#/$defs/{ref_prefix}/{{model}}",
    )
    defs = top.get("$defs", {})

    out: dict[str, Any] = {}
    for name, cls in events.items():
        model_name = cls.__name__
        schema = defs.pop(model_name, None)
        if schema is None:
            schema = cls.model_json_schema(schema_generator=GenerateJsonSchema)
        out[name] = schema
    return out, defs


def build_schema() -> dict[str, Any]:
    client_schemas, client_defs = _schemas_for(CLIENT_EVENTS, "client")
    server_schemas, server_defs = _schemas_for(SERVER_EVENTS, "server")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Bughouse websocket events",
        "client": client_schemas,
        "server": server_schemas,
        "$defs": {
            "client": client_defs,
            "server": server_defs,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate websocket event JSON schema")
    parser.add_argument(
        "-o", "--output",
        default="docs/ws_events.schema.json",
        help="Output path (default: docs/ws_events.schema.json)",
    )
    args = parser.parse_args()

    schema = build_schema()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

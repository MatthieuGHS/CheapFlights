"""API locale (§13) : lancer une recherche, suivre sa progression en SSE, lire résultats et santé.

Un seul utilisateur, un seul process : les recherches en cours vivent en mémoire.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from cheaphops.core.config import Config, load_config, load_ground
from cheaphops.core.db import connect
from cheaphops.core.models import SearchParams
from cheaphops.recipes.registry import load
from cheaphops.search.engine import Event, SearchResult, run_search

SearchFn = Callable[..., Awaitable[SearchResult]]
WEB_DIST = Path(__file__).parent.parent.parent / "web" / "dist"


class SearchRequest(BaseModel):
    preset: str | None = None
    overrides: dict[str, Any] = {}  # champs de SearchParams, validés à la création


@dataclass
class Run:
    id: str
    params: SearchParams
    events: list[Event] = field(default_factory=list)
    result: SearchResult | None = None
    error: str | None = None
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def push(self, event: Event) -> None:
        """Synchrone : les événements gardent l'ordre où le moteur les émet."""
        self.events.append(event | {"at": datetime.now(UTC).isoformat()})
        self.changed.set()


def create_app(
    config_path: Path = Path("config.yaml"),
    ground_path: Path = Path("ground.yaml"),
    search: SearchFn = run_search,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    app = FastAPI(title="Cheap Hops")
    runs: dict[str, Run] = {}
    local_path = config_path.with_name("config.local.yaml")

    def params_for(req: SearchRequest, config: Config) -> SearchParams:
        if req.preset and req.preset not in config.search.presets:
            raise HTTPException(422, f"unknown preset {req.preset}")
        defaults = config.search.presets[req.preset] if req.preset else config.search.defaults
        try:
            return SearchParams.model_validate(
                defaults.params(today()).model_dump() | req.overrides
            )
        except ValidationError as e:
            raise HTTPException(422, json.loads(e.json())) from e

    async def execute(run: Run, config: Config) -> None:
        conn = connect(config.db_path)
        try:
            run.result = await search(
                run.params, config, load_ground(ground_path), conn, today(), run.push
            )
        except Exception as e:  # une recherche qui plante ne doit pas tuer le serveur
            run.error = f"{type(e).__name__}: {e}"
        finally:
            conn.close()
        run.done = True
        run.push({"type": "finished", "error": run.error})

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        config = load_config(config_path)
        body: dict[str, Any] = jsonable_encoder(
            {
                "defaults": config.search.defaults,
                "presets": config.search.presets,
                "request_budget": config.search.request_budget,
            }
        )
        return body

    @app.put("/api/config/defaults")
    def save_defaults(overrides: dict[str, Any]) -> dict[str, Any]:
        """Réglages de l'UI : écrits dans config.local.yaml, jamais dans config.yaml (§2.6)."""
        local = yaml.safe_load(local_path.read_text()) if local_path.exists() else {}
        local = local or {}
        defaults = local.setdefault("search", {}).setdefault("defaults", {})
        defaults.update(jsonable_encoder(overrides))
        previous = local_path.read_text() if local_path.exists() else None
        local_path.write_text(yaml.safe_dump(local, allow_unicode=True, sort_keys=False))
        try:
            return get_config()
        except ValidationError as e:  # réglage invalide : on remet le fichier tel qu'il était
            if previous is None:
                local_path.unlink()
            else:
                local_path.write_text(previous)
            raise HTTPException(422, json.loads(e.json())) from e

    @app.post("/api/searches")
    async def start(req: SearchRequest) -> dict[str, str]:
        config = load_config(config_path)
        run = Run(uuid.uuid4().hex[:12], params_for(req, config))
        runs[run.id] = run
        run.task = asyncio.create_task(execute(run, config))  # référence gardée : pas de GC
        return {"id": run.id}

    def get_run(run_id: str) -> Run:
        if run_id not in runs:
            raise HTTPException(404, "unknown search")
        return runs[run_id]

    @app.get("/api/searches/{run_id}")
    def status(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        r = run.result
        body: dict[str, Any] = jsonable_encoder({
            "id": run.id, "done": run.done, "error": run.error, "params": run.params,
            "trips": r.trips if r else [], "requests": r.requests if r else None,
            "budget_exhausted": r.budget_exhausted if r else None,
            "candidates": r.candidates if r else None, "pruned": r.pruned if r else None,
        })  # fmt: skip
        return body

    @app.get("/api/searches/{run_id}/events")
    async def events(run_id: str) -> StreamingResponse:
        run = get_run(run_id)

        async def stream() -> AsyncIterator[str]:
            sent = 0
            while True:
                run.changed.clear()
                batch = run.events[sent:]
                if not batch:
                    await run.changed.wait()
                    continue
                for event in batch:
                    yield f"data: {json.dumps(jsonable_encoder(event))}\n\n"
                sent += len(batch)
                if batch[-1]["type"] == "finished":
                    return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/sources")
    def sources() -> list[dict[str, Any]]:
        config = load_config(config_path)
        with closing(connect(config.db_path)) as conn:
            out = []
            for name in config.search.sources:
                m = load(name).manifest
                state = conn.execute(
                    "SELECT blocked_until, reason FROM source_state WHERE source = ?", (name,)
                ).fetchone()
                rungs = conn.execute(
                    "SELECT rung, successes, failures, browser_requests, last_failure"
                    " FROM fetch_stats WHERE source = ? ORDER BY rung", (name,),
                ).fetchall()  # fmt: skip
                out.append({
                    "source": name, "version": m.version, "status": m.status,
                    "capabilities": sorted(m.capabilities), "preferred_rung": m.preferred_rung,
                    "blocked_until": state["blocked_until"] if state else None,
                    "blocked_reason": state["reason"] if state else None,
                    "rungs": [dict(r) for r in rungs],
                })  # fmt: skip
        return out

    if WEB_DIST.exists():  # interface construite (npm run build) servie à la racine
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app

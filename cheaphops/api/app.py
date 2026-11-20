"""API locale : lancer une recherche dernière minute, suivre sa progression en SSE, lire le
résultat. Un seul utilisateur, un seul process : les recherches vivent en mémoire."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from cheaphops.core.config import Ground, LastMinute, load_config, load_ground, with_overrides
from cheaphops.lastminute.run import Emit, Result, run

SearchFn = Callable[[LastMinute, Ground, date, Emit], Awaitable[Result]]
WEB_DIST = Path(__file__).parent.parent.parent / "web" / "dist"


class SearchRequest(BaseModel):
    days: int | None = None
    origins: list[str] | None = None
    max_nights: int | None = None
    google: bool | None = None
    weekend: bool | None = None


@dataclass
class Run:
    id: str
    params: LastMinute
    events: list[dict[str, Any]] = field(default_factory=list)
    result: Result | None = None
    error: str | None = None
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def push(self, event: dict[str, Any]) -> None:
        self.events.append(event | {"at": datetime.now(UTC).isoformat()})
        self.changed.set()


def create_app(
    config_path: Path = Path("config.yaml"),
    ground_path: Path = Path("ground.yaml"),
    search: SearchFn = run,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    app = FastAPI(title="Cheap Hops")
    runs: dict[str, Run] = {}

    async def execute(r: Run) -> None:
        try:
            r.result = await search(r.params, load_ground(ground_path), today(), r.push)
        except Exception as e:  # une recherche qui plante ne doit pas tuer le serveur
            r.error = f"{type(e).__name__}: {e}"
        finally:
            r.done = True
            r.push({"type": "done", "error": r.error})

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return jsonable_encoder(load_config(config_path).lastminute)  # type: ignore[no-any-return]

    @app.post("/api/searches")
    async def start(req: SearchRequest) -> dict[str, str]:
        base = load_config(config_path).lastminute
        update = req.model_dump(exclude_none=True)
        if "google" in update:
            update["google"] = {"enabled": update["google"]}
        try:
            params = with_overrides(base, update)
        except ValidationError as e:
            raise HTTPException(422, json.loads(e.json())) from e
        r = Run(uuid.uuid4().hex[:12], params)
        runs[r.id] = r
        r.task = asyncio.create_task(execute(r))  # référence gardée : pas de GC
        return {"id": r.id}

    def get_run(run_id: str) -> Run:
        if run_id not in runs:
            raise HTTPException(404, "unknown search")
        return runs[run_id]

    @app.get("/api/searches/{run_id}")
    def status(run_id: str) -> dict[str, Any]:
        r = get_run(run_id)
        body: dict[str, Any] = jsonable_encoder(
            {"id": r.id, "done": r.done, "error": r.error, "params": r.params, "result": r.result}
        )
        return body

    @app.get("/api/searches/{run_id}/events")
    async def events(run_id: str) -> StreamingResponse:
        r = get_run(run_id)

        async def stream() -> AsyncIterator[str]:
            sent = 0
            while True:
                r.changed.clear()
                batch = r.events[sent:]
                if not batch:
                    await r.changed.wait()
                    continue
                for event in batch:
                    yield f"data: {json.dumps(jsonable_encoder(event))}\n\n"
                sent += len(batch)
                if batch[-1]["type"] == "done":
                    return

        return StreamingResponse(stream(), media_type="text/event-stream")

    if WEB_DIST.exists():  # interface construite (npm run build) servie à la racine
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app

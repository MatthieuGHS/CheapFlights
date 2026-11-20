import asyncio
from datetime import date

from fastapi.testclient import TestClient

from cheaphops.api.app import create_app
from cheaphops.core.config import Ground, LastMinute
from cheaphops.lastminute.run import Emit, Result


def test_search_validates_runs_one_at_a_time_and_streams_until_done() -> None:
    release = asyncio.Event()
    seen: list[LastMinute] = []

    async def search(cfg: LastMinute, ground: Ground, today: date, emit: Emit) -> Result:
        seen.append(cfg)
        await release.wait()
        raise RuntimeError("source en panne")

    with TestClient(create_app(search=search)) as c:
        assert c.post("/api/searches", json={"days": 100}).status_code == 422
        past = {"periods": [{"start": "2020-01-01", "end": "2020-01-03"}]}
        assert c.post("/api/searches", json=past).status_code == 422
        r = c.post("/api/searches", json={"days": 5, "google": True, "origins": ["RIX"]})
        assert r.status_code == 200
        run_id = r.json()["id"]
        assert c.post("/api/searches", json={}).status_code == 409
        c.portal.call(release.set)  # type: ignore[union-attr]
        events = c.get(f"/api/searches/{run_id}/events").text
        assert '"type": "done"' in events
        body = c.get(f"/api/searches/{run_id}").json()
        assert (body["done"], body["error"]) == (True, "RuntimeError: source en panne")
        assert c.get("/api/searches/inconnu").status_code == 404
    assert (seen[0].days, seen[0].google.enabled, seen[0].origins) == (5, True, ["RIX"])

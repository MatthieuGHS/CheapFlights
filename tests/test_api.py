import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from cheaphops.api.app import create_app
from cheaphops.core.config import Ground, LastMinute
from cheaphops.lastminute.fares import Bus, Fare, RoundTrip
from cheaphops.lastminute.run import Emit, PeriodResult, Result


def test_search_validates_runs_one_at_a_time_and_streams_until_done(tmp_path: Path) -> None:
    release = asyncio.Event()
    seen: list[LastMinute] = []

    async def search(cfg: LastMinute, ground: Ground, today: date, emit: Emit) -> Result:
        seen.append(cfg)
        await release.wait()
        raise RuntimeError("source en panne")

    with TestClient(create_app(search=search, history_dir=tmp_path)) as c:
        assert c.post("/api/searches", json={"days": 100}).status_code == 422
        past = {"periods": [{"start": "2020-01-01", "end": "2020-01-03"}]}
        assert c.post("/api/searches", json=past).status_code == 422
        typo = c.post("/api/searches", json={"destinations": ["BGY", "XQZ"]})
        assert (typo.status_code, typo.json()["detail"]) == (422, "aéroport inconnu : XQZ")
        r = c.post(
            "/api/searches", json={"days": 5, "google": True, "kiwi": False, "origins": ["RIX"]}
        )
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
    assert (seen[0].kiwi.enabled, seen[0].kiwi.returns) == (False, 10)  # le reste gardé


def test_finished_search_keeps_its_top_10_on_disk(tmp_path: Path) -> None:
    def leg(o: str, d: str, day: int, price: int) -> Fare:
        when = datetime(2026, 12, day, 8)
        return Fare("ryanair", "Ryanair", o, d, when, Decimal(price), None, f"https://r/{o}{d}")

    no_bus = Bus(Decimal(0), 0)
    trips = [RoundTrip(leg("VNO", f"D{i:02d}", 3, 20 + i), leg(f"D{i:02d}", "VNO", 5, 10), no_bus)
             for i in range(12)]  # fmt: skip
    period = PeriodResult(date(2026, 12, 2), date(2026, 12, 6), trips, {}, {})

    async def search(cfg: LastMinute, ground: Ground, today: date, emit: Emit) -> Result:
        return Result([t.out for t in trips], [period], [], {}, {"VNO": "Vilnius"}, 13, 1.0)

    with TestClient(create_app(search=search, history_dir=tmp_path)) as c:
        run_id = c.post("/api/searches", json={}).json()["id"]
        c.get(f"/api/searches/{run_id}/events")
        (entry,) = c.get("/api/history").json()
        assert (entry["id"], entry["best"], entry["count"]) == (run_id, 30, 10)
        saved = c.get(f"/api/history/{run_id}").json()["result"]
        assert len(saved["periods"][0]["roundtrips"]) == len(saved["oneways"]) == 10
        assert saved["periods"][0]["roundtrips"][0]["out"]["url"] == "https://r/VNOD00"
        assert c.get("/api/history/..%2F..%2Fconfig").status_code == 404


def test_airport_table_is_served_compressed_with_french_city_names(tmp_path: Path) -> None:
    with TestClient(create_app(history_dir=tmp_path)) as c:
        r = c.get("/api/airports")
    assert r.headers["content-encoding"] == "gzip"  # httpx décompresse : le corps est le JSON
    table = {a["iata"]: a for a in r.json()}
    assert (table["BGY"]["city"], table["BGY"]["country"]) == ("Bergame", "IT")
    assert table["WMI"]["city"] == "Varsovie" and "Warsaw" in table["WMI"]["alt"]

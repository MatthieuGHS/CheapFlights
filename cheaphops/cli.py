"""cheaphops search : dernière minute partout, récap en quelques lignes. cheaphops serve : l'UI."""

import argparse
import asyncio
import sys
from datetime import date

from cheaphops.core.config import load_config, load_ground
from cheaphops.core.log import setup_logging
from cheaphops.lastminute.fares import Fare, RoundTrip
from cheaphops.lastminute.run import Result, run


def _fare(f: Fare) -> str:
    fmt = "%a %d/%m" if f.source == "wizzair" else "%a %d/%m %H:%M"  # Wizz : prix au jour
    return f"{f.origin}->{f.destination} {f.departure.strftime(fmt)} {f.airline} {f.price} €"


def render(r: Result, top: int = 10) -> str:
    lines = [f"{r.seconds:.0f} s, {r.requests} requêtes"]
    for name, s in r.sources.items():
        state = f"ERREUR {s.error}" if s.error else f"ok{f' ({s.mode})' if s.mode else ''}"
        lines.append(
            f"  {name}: {state}, {s.fares} tarifs ({s.in_window} dans la fenêtre), "
            f"{s.requests} req, {s.seconds:.0f} s"
        )
    lines.append(f"Top {top} aller-retours :")
    lines += [_trip(t) for t in r.roundtrips[:top]] or ["  (aucun)"]
    lines.append(f"Top {top} allers simples :")
    lines += [f"  {_fare(f)}" for f in r.oneways[:top]]
    if r.deals:
        lines.append("Bons plans (sans date précise) :")
        lines += [f"  {d.price} € {d.origin}->{d.destination} {d.url}" for d in r.deals[:top]]
    return "\n".join(lines)


def _trip(t: RoundTrip) -> str:
    return f"  {t.total} € / {t.nights} n : {_fare(t.out)} | {_fare(t.back)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheaphops")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="dernière minute depuis les origines vers partout")
    s.add_argument("--days", type=int, help="départs de J+0 à J+N, 60 max (défaut : config)")
    s.add_argument(
        "--google", action="store_true", help="active Google Flights (hubs échantillonnés)"
    )
    s.add_argument("--origins", help="ex. VNO,KUN,RIX,WAW (optionnels : WAW, GDN, TLL)")
    srv = sub.add_parser("serve", help="API + interface web sur http://127.0.0.1:PORT")
    srv.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    config = load_config()
    setup_logging(config.log_level)
    if args.command == "serve":
        import uvicorn

        from cheaphops.api.app import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=args.port)  # local uniquement
        return 0

    lm = config.lastminute
    update = {
        k: v
        for k, v in (
            ("days", args.days),
            ("origins", args.origins.split(",") if args.origins else None),
        )
        if v is not None
    }
    lm = lm.model_copy(update=update)
    if args.google:
        lm = lm.model_copy(update={"google": lm.google.model_copy(update={"enabled": True})})
    print(
        render(
            asyncio.run(run(lm, load_ground(), date.today(), lambda e: print(e, file=sys.stderr)))
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

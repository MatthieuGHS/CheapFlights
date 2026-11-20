"""cheaphops search : dernière minute partout, récap en quelques lignes. cheaphops serve : l'UI."""

import argparse
import asyncio
import sys
from datetime import date

from pydantic import ValidationError

from cheaphops.core.config import load_config, load_ground, with_overrides
from cheaphops.core.log import setup_logging
from cheaphops.lastminute.fares import Fare, RoundTrip, best_per_route
from cheaphops.lastminute.run import Result, run


def _fare(f: Fare) -> str:
    fmt = "%a %d/%m" if f.source == "wizzair" else "%a %d/%m %H:%M"  # Wizz : prix au jour
    line = f"{f.origin}->{f.destination} {f.departure.strftime(fmt)} {f.airline} {f.price} €"
    return f"{line} [{f.source}, {'indicatif' if f.indicative else 'vérifié'}]"


def render(r: Result, top: int = 10, all_dates: bool = False) -> str:
    lines = [f"{r.seconds:.0f} s, {r.requests} requêtes"]
    for name, s in r.sources.items():
        state = f"ERREUR {s.error}" if s.error else f"ok{f' ({s.mode})' if s.mode else ''}"
        lines.append(
            f"  {name}: {state}, {s.fares} tarifs ({s.in_window} dans la fenêtre), "
            f"{s.requests} req, {s.seconds:.0f} s"
        )
    lines.append(f"Top {top} aller-retours (une ligne par destination) :")
    for t in r.roundtrips[:top] or []:
        lines.append(_trip(t))
        if all_dates:
            lines += [
                f"      {_trip(x).strip()}" for x in r.alternatives.get(t.out.destination, [])[1:]
            ]
    if not r.roundtrips:
        lines.append("  (aucun)")
    lines.append(f"Top {top} allers simples (meilleure date par route) :")
    lines += [f"  {_fare(f)}" for f in best_per_route(r.oneways)[:top]]
    if r.deals:
        lines.append("Bons plans (aller-retour, dates si connues) :")
        lines += [
            f"  {d.price} € {d.origin}->{d.destination} {d.when or ''} {d.airline or ''} "
            f"[{d.source}]"
            for d in r.deals[:top]
        ]
    return "\n".join(lines)


def _bus(t: RoundTrip) -> str:
    b = t.bus
    return f"  [bus info : {b.cost} € / {b.minutes // 60} h {b.minutes % 60:02d}]" if b.cost else ""


def _trip(t: RoundTrip) -> str:
    check = "  (heure de retour à vérifier)" if t.check_return else ""
    if t.bundled:
        legs = f"{_fare(t.out)} (aller-retour, {t.back.day:%d/%m})"
    else:
        legs = f"{_fare(t.out)} | {_fare(t.back)}"
    return f"  {t.total} € (vols) / {t.nights} n : {legs}{check}{_bus(t)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheaphops")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="dernière minute depuis les origines vers partout")
    s.add_argument("--days", type=int, help="départs de J+0 à J+N, 60 max (défaut : config)")
    s.add_argument(
        "--google", action="store_true", help="active Google Flights (hubs échantillonnés)"
    )
    s.add_argument(
        "--weekend", action="store_true", help="départ vendredi/samedi, retour dimanche/lundi matin"
    )
    s.add_argument(
        "--all-dates", action="store_true", help="toutes les dates de chaque destination"
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

    update = {
        "days": args.days,
        "origins": args.origins.split(",") if args.origins else None,
        "weekend": True if args.weekend else None,
        "google": {"enabled": True} if args.google else None,
    }
    try:
        lm = with_overrides(config.lastminute, {k: v for k, v in update.items() if v is not None})
    except ValidationError as e:
        ap.error(str(e))
    result = asyncio.run(run(lm, load_ground(), date.today(), lambda e: print(e, file=sys.stderr)))
    print(render(result, all_dates=args.all_dates))
    return 0


if __name__ == "__main__":
    sys.exit(main())

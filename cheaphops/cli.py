"""cheaphops search : dernière minute partout, récap en quelques lignes. cheaphops serve : l'UI."""

import argparse
import asyncio
import sys
from datetime import date

from pydantic import ValidationError

from cheaphops.core.config import load_config, load_ground, with_overrides
from cheaphops.core.log import setup_logging
from cheaphops.lastminute.fares import Fare, RoundTrip, best_per_route
from cheaphops.lastminute.run import Result, run, windows_for


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
    for p in r.periods:
        lines.append(
            f"Top {top} aller-retours du {p.start:%d/%m} au {p.end:%d/%m} (un par destination) :"
        )
        for t in p.roundtrips[:top]:
            lines.append(_trip(t))
            if all_dates:
                lines += [
                    f"      {_trip(x).strip()}"
                    for x in p.alternatives.get(t.out.destination, [])[1:]
                ]
        if not p.roundtrips:
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


def _periods(text: str) -> list[dict[str, str]]:
    """« 2026-11-20:2026-11-26,2026-12-25 » -> plages ; un jour seul est une plage d'un jour."""
    out = []
    for part in text.split(","):
        bounds = [b.strip() for b in part.split(":")]
        if len(bounds) > 2:
            raise ValueError(f"plage « {part.strip()} » : début:fin attendu")
        out.append({"start": bounds[0], "end": bounds[-1]})
    return out


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
    s.add_argument(
        "--dates", help="plages précises, ex. 2026-11-20:2026-11-26,2026-12-30:2027-01-02"
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

    try:
        update = {
            "days": args.days,
            "origins": [o.strip().upper() for o in args.origins.split(",") if o.strip()] or None
            if args.origins
            else None,
            "weekend": True if args.weekend else None,
            "google": {"enabled": True} if args.google else None,
            # --days seul repasse en mode « J+0 à J+days », même si la config a des plages
            "periods": _periods(args.dates) if args.dates
                       else [] if args.days is not None else None,
        }  # fmt: skip
        lm = with_overrides(config.lastminute, {k: v for k, v in update.items() if v is not None})
        windows_for(lm, date.today())
    except (ValidationError, ValueError) as e:
        ap.error(str(e))
    result = asyncio.run(run(lm, load_ground(), date.today(), lambda e: print(e, file=sys.stderr)))
    print(render(result, all_dates=args.all_dates))
    return 0


if __name__ == "__main__":
    sys.exit(main())

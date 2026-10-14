from datetime import datetime, timedelta, timezone


def local_aware(local_iso: str, utc_iso: str) -> datetime:
    """Heure locale de l'aéroport, avec son décalage réel déduit de l'heure UTC du même instant.
    `2026-11-04T11:25:00.000` + `2026-11-04T09:25:00.000Z` -> 11:25+02:00."""
    local = datetime.fromisoformat(local_iso.removesuffix("Z")).replace(tzinfo=None)
    utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).replace(tzinfo=None)
    return local.replace(tzinfo=timezone(local - utc))


def with_offset(local_iso: str, offset: str) -> datetime:
    """`2026-11-13T05:55:00` + `02:00:00` (ou `-05:00:00`) -> 05:55+02:00."""
    sign = -1 if offset.startswith("-") else 1
    h, m, *_ = (int(x) for x in offset.lstrip("+-").split(":"))
    delta = sign * timedelta(hours=h, minutes=m)
    return datetime.fromisoformat(local_iso).replace(tzinfo=timezone(delta))

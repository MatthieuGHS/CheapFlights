from datetime import datetime, timezone


def local_aware(local_iso: str, utc_iso: str) -> datetime:
    """Heure locale de l'aéroport, avec son décalage réel déduit de l'heure UTC du même instant.
    `2026-11-04T11:25:00.000` + `2026-11-04T09:25:00.000Z` -> 11:25+02:00."""
    local = datetime.fromisoformat(local_iso.removesuffix("Z")).replace(tzinfo=None)
    utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).replace(tzinfo=None)
    return local.replace(tzinfo=timezone(local - utc))

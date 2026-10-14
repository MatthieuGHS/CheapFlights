from datetime import timedelta

from cheaphops.skills.timeparse import local_aware


def test_local_aware_keeps_wall_clock_with_real_offset() -> None:
    dt = local_aware(
        "2026-03-29T03:30:00.000", "2026-03-29T00:30:00.000Z"
    )  # passage à l'heure d'été
    assert dt.hour == 3 and dt.utcoffset() == timedelta(hours=3)


def test_with_offset_handles_negative_offsets() -> None:
    from cheaphops.skills.timeparse import with_offset

    assert with_offset("2026-11-13T05:55:00", "02:00:00").isoformat() == "2026-11-13T05:55:00+02:00"
    assert with_offset("2026-11-13T05:55:00", "-05:30:00").utcoffset() == -timedelta(
        hours=5, minutes=30
    )

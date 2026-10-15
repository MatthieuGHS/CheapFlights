"""Capture recon en navigateur VISIBLE : tu navigues à la main, toutes les réponses JSON sont
enregistrées dans data/recon/<nom>/ (index.json : url, statut, taille ; un fichier par réponse).

    uv run python -m cheaphops.lastminute.recon kiwi https://www.kiwi.com/en/ [secondes=180]

Seul usage prévu d'une fenêtre visible, à la demande, pour comprendre un site que Scrapling
n'atteint pas en automatique (formats d'URL, requêtes GraphQL). Ferme la fenêtre pour finir.
"""

import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> None:
    from patchright.sync_api import sync_playwright

    name, url = argv[0], argv[1]
    seconds = int(argv[2]) if len(argv) > 2 else 180
    out = Path("data/recon") / name
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []

    def on_response(r: object) -> None:
        try:
            ctype = r.headers.get("content-type", "")  # type: ignore[attr-defined]
            if "json" not in ctype:
                return
            body = r.text()  # type: ignore[attr-defined]
            n = len(index)
            (out / f"resp_{n:03d}.json").write_text(body)
            index.append({"n": n, "url": r.url, "status": r.status, "bytes": len(body)})  # type: ignore[attr-defined]
        except Exception:
            pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("response", on_response)
        page.goto(url)
        deadline = time.time() + seconds
        while time.time() < deadline and not page.is_closed():
            page.wait_for_timeout(1000)
        browser.close()
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"{len(index)} réponses JSON dans {out}")


if __name__ == "__main__":
    main(sys.argv[1:])

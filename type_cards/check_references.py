"""Check every reference the type cards cite, online, and write type_cards/references_checked.json (committed; the offline test
holds every Reference to it).

    python3 /home/bam/sim2real/type_cards/check_references.py

Stdlib only. For each DOI: Crossref's record (title, year, venue, authors), and doi.org's handle API (the DOI resolves). For each
URL: a doi.org URL is checked through that same handle API (publishers refuse automated fetches, so their page is not the test);
any other URL is fetched (GET, redirects followed) and passes on a 2xx. Sequential with a pause, to stay inside Crossref's
polite rate.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from type_cards import references as refs  # noqa: E402
from type_cards import registry as reg  # noqa: E402

OUT = Path(__file__).resolve().parent / "references_checked.json"
AGENT = "sim2real-type-cards/2 (reference check; https://github.com/zacharyyamaoka)"
PAUSE_S = 1.2


def used() -> list:
    out = list(refs.ALL)
    for card in reg.CARDS.values():
        out += [ref for r in card.rungs for ref in r.references]
    out += [ref for p in reg.CALIBRATION_PACKAGES for ref in p.references]
    out += [ref for law in reg.WEAR_LAW_REFERENCES.values() for ref in law]
    seen, unique = set(), []
    for ref in out:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def get(url: str, accept: str = "*/*") -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read(400_000), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except Exception as e:  # noqa: BLE001  (a timeout or DNS failure is a failed check, recorded)
        return 0, str(e).encode(), url


def crossref(doi: str) -> dict:
    status, body, _ = get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""), "application/json")
    if status != 200:
        return {"ok": False, "status": status}
    m = json.loads(body)["message"]
    return {"ok": True, "title": (m.get("title") or [""])[0], "year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "venue": (m.get("container-title") or [""])[0], "authors": [a.get("family", "") for a in m.get("author", [])][:8],
            "volume": m.get("volume", ""), "page": m.get("page", "")}


def handle(doi: str) -> dict:
    status, body, _ = get("https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/"), "application/json")
    code = json.loads(body).get("responseCode") if status == 200 else None
    return {"ok": code == 1, "status": status, "via": "doi.org handle API", "response_code": code}


def main() -> int:
    today = time.strftime("%Y-%m-%d")
    out = {"checked": today, "how": __doc__.splitlines()[0], "doi": {}, "url": {}}
    failed = []
    for ref in used():
        if ref.doi and ref.doi not in out["doi"]:
            hit = crossref(ref.doi)
            resolves = handle(ref.doi)
            hit["resolves"] = resolves["ok"]
            hit["ok"] = hit["ok"] and resolves["ok"]
            out["doi"][ref.doi] = hit
            time.sleep(PAUSE_S)
            if not hit["ok"]:
                failed.append(ref.doi)
        if ref.url and ref.url not in out["url"]:
            if ref.url.startswith("https://doi.org/"):
                doi = ref.url[len("https://doi.org/"):]
                res = handle(doi)
            else:
                status, _body, final = get(ref.url, "text/html,*/*")
                res = {"ok": 200 <= status < 300, "status": status, "final": final, "via": "GET"}
            out["url"][ref.url] = res
            time.sleep(PAUSE_S)
            if not res["ok"]:
                failed.append(ref.url)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(out['doi'])} DOIs, {len(out['url'])} URLs checked -> {OUT}; failed: {failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

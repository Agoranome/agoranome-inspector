"""Build examples/demo-site: two weeks of a small FAKE market, published and signed, so anyone can try the
verifier without running the measurer. Every host is under example.*; none is a real seller.

  python scripts/demo_site.py            (rebuilds examples/demo-site with a new throwaway key)
  agoranome-inspector verify examples/demo-site --all
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from agoranome_inspector import sheet as sheet_lib  # noqa: E402
from agoranome_inspector.keys import Signer  # noqa: E402
from agoranome_inspector.measure import Settings, run  # noqa: E402
from agoranome_inspector import shelf  # noqa: E402
from agoranome_inspector.book import Book  # noqa: E402
from agoranome_inspector.publish import BOOK, note, publish, write_head, write_index, write_shelves  # noqa: E402
from fakes import OTHER, honest, standard_market  # noqa: E402


def week(market, run_id):
    found = run(run_id, reader=market.reader(), fetcher=market.fetcher(),
                settings=Settings(concurrency=1, host_pause=0, retry_pause=0, confirm_pause=0), clock=lambda: f"{run_id[-10:]}T06:00:00Z")
    found["index"]["url"] = "https://index.example/discovery/resources (a fake index)"
    built = sheet_lib.build(found["id"], found["listings"], found["seen"], index=found["index"], probe=found["probe"])
    return built, {x["resource"]: x["words"] for x in found["listings"]}


def main() -> None:
    site = ROOT / "examples" / "demo-site"
    shutil.rmtree(site, ignore_errors=True)
    signer = Signer.generate()   # thrown away: the demo book can never be extended
    market = standard_market()
    built, words = week(market, "x402-2026-11-16")
    publish(str(site), built, signer, time="2026-11-16T07:00:00Z", words=words)
    note(str(site), signer, "A demo book over a fake market. No host in it is a real seller.",
         time="2026-11-16T07:01:00Z")
    market.sellers["pricey.example"] = honest("5000")
    market.sellers["swap.example"] = honest("5000", OTHER.replace("2", "3"))
    market.sellers["gone.example"] = honest("1000")
    built, words = week(market, "x402-2026-11-23")
    publish(str(site), built, signer, time="2026-11-23T07:00:00Z", words=words)
    book = Book(str(site / BOOK))
    book.append(signer, "shelf", shelf.shelf_body(book.entries()), time="2026-11-23T07:05:00Z")
    write_shelves(site, book)
    write_index(site, book)
    write_head(site, book)
    print(f"demo site written to {site.relative_to(ROOT)}; first key {signer.kid}")


if __name__ == "__main__":
    main()

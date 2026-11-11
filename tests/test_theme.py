"""The pages people read wear agoranome.com's theme (Shariar 2026-11-11), and `pages` rewrites them from the book
without touching it."""

import json

from agoranome_inspector import bestbuy, theme
from agoranome_inspector.cli import main
from agoranome_inspector.keys import Signer
from agoranome_inspector.publish import publish
from agoranome_inspector.verify import verify

from fakes import standard_market
from test_markets import measure


def test_the_sheet_page_wears_the_sites_theme(tmp_path):
    publish(str(tmp_path), measure(standard_market(), "x402-2026-11-16"), Signer.generate())
    page = (tmp_path / "index.html").read_text()
    # The site's frame: its stylesheet and mark beside the page, its header and footer linking agoranome.com.
    assert '<link rel="stylesheet" href="style.css">' in page and '<img src="mark.svg"' in page
    assert f'<a class="brand" href="{theme.HOME}"' in page and theme.INSPECTOR_PAGE in page
    assert '<a href="index.html" aria-current="page">Open sheet</a>' in page
    assert '<p class="eyebrow">Agoranome inspector</p>' in page and '<p class="lead">' in page
    assert 'class="site-footer"' in page and "<style>" not in page
    # No best-buy sheet yet, so the menu doesn't offer one.
    assert "best-buy/index.html" not in page
    # The same figures as before, and the files the page needs, with nothing fetched from another origin.
    assert "x402: sheet x402-2026-11-16" in page and "Check it yourself" in page
    assert (tmp_path / "style.css").read_text() == theme.CSS and "--page: #0a121b" in theme.CSS
    assert (tmp_path / "mark.svg").read_text().startswith("<svg")
    assert "@import" not in theme.CSS and "url(http" not in theme.CSS


def test_a_page_one_folder_down_reaches_the_theme_and_the_sheet():
    page = bestbuy.page({"categories": []}, "best-buy/2026-11-16-abc.json")
    assert '<link rel="stylesheet" href="../style.css">' in page and '<img src="../mark.svg"' in page
    assert '<a href="../index.html">Open sheet</a>' in page
    assert '<a href="../best-buy/index.html" aria-current="page">Best buys</a>' in page
    assert 'class="doc doc-wide"' in page and "Best buys, by kind of job" in page


def test_pages_rewrites_the_look_and_never_the_book(tmp_path, capsys):
    publish(str(tmp_path), measure(standard_market(), "x402-2026-11-16"), Signer.generate())
    book = (tmp_path / "book.jsonl").read_bytes()
    (tmp_path / "index.html").write_text("<html>an old page</html>", encoding="utf-8")
    (tmp_path / "style.css").unlink()
    assert main(["pages", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"index": True, "best_buy": False}
    assert (tmp_path / "book.jsonl").read_bytes() == book
    assert "The open sheet" in (tmp_path / "index.html").read_text() and (tmp_path / "style.css").exists()
    assert verify(str(tmp_path), every=True).ok
    assert main(["pages", str(tmp_path / "nowhere")]) == 2

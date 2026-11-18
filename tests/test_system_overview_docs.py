from pathlib import Path
import re
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href")


def test_exported_overviews_are_product_documents_with_responsive_layout():
    paths = list((ROOT / "docs/public").glob("*.html"))
    assert paths
    for path in paths:
        text = path.read_text()
        parser = PageParser()
        parser.feed(text)
        assert {"html", "main", "nav", "h1", "table"}.issubset(parser.tags)
        assert 'name="viewport"' in text
        assert "@media(max-width:600px)" in text
        assert "@media print" in text
        assert "REFALL AB" in text
        assert re.search(r"/(?:Users|home)/[^/\s\"'`<>]+", text) is None
        for private in ["192.168.30.13", "PRIVATE - INTERNAL", "Public - redacted - showcase"]:
            assert private not in text
        for link in parser.links:
            if not link.startswith(("http:", "https:", "#")):
                assert (path.parent / link.split("#")[0]).exists(), (path, link)

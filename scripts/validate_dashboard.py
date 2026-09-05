"""Validate that the static dashboard has its required assets and DOM contract."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.local_assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.append(element_id)
        source = None
        if tag == "script":
            source = attributes.get("src")
        elif tag == "link":
            source = attributes.get("href")
        if source and source.startswith("/"):
            self.local_assets.append(source)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = root / "dashboard"
    parser = DashboardParser()
    parser.feed((dashboard / "index.html").read_text(encoding="utf-8"))

    required_ids = {
        "api-url",
        "connect-button",
        "request-form",
        "request-result",
        "latency-chart",
        "provider-list",
        "event-table",
    }
    missing = required_ids.difference(parser.ids)
    if missing:
        raise SystemExit(f"dashboard is missing required elements: {sorted(missing)}")
    if len(parser.ids) != len(set(parser.ids)):
        raise SystemExit("dashboard contains duplicate element IDs")

    missing_assets = [
        asset for asset in parser.local_assets if not (dashboard / asset.lstrip("/")).is_file()
    ]
    if missing_assets:
        raise SystemExit(f"dashboard references missing local assets: {missing_assets}")

    print(
        f"Dashboard validation passed: {len(parser.ids)} IDs, "
        f"{len(parser.local_assets)} local assets"
    )


if __name__ == "__main__":
    main()

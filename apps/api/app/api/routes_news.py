"""API routes for oil news feed (RSS proxy to avoid CORS)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from fastapi import APIRouter, Query

router = APIRouter(prefix="/news", tags=["news"])

RSS_FEEDS = {
    "eia": {
        "url": "https://www.eia.gov/rss/todayinenergy.xml",
        "name": "EIA Today in Energy",
        "name_fr": "EIA — L'énergie aujourd'hui",
        "lang": "en",
    },
    "oilprice": {
        "url": "https://oilprice.com/rss/main",
        "name": "OilPrice.com",
        "name_fr": "OilPrice.com",
        "lang": "en",
    },
}


def _parse_rss(xml_text: str, source_id: str, source_name: str) -> list[dict[str, Any]]:
    """Parse RSS XML into a list of article dicts."""
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            description = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            if not title:
                continue

            # Clean up HTML from description
            if "<" in description:
                description = re.sub(r"<[^>]+>", "", description).strip()
            if len(description) > 300:
                description = description[:297] + "..."

            items.append({
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
                "source_id": source_id,
                "source_name": source_name,
            })
    except ET.ParseError:
        pass
    return items


@router.get("")
async def get_news(
    limit: int = Query(20, ge=1, le=50),
    source: str | None = Query(None, description="Filter by source id: eia, oilprice"),
):
    """Fetch and return oil news from free RSS feeds."""
    all_items: list[dict[str, Any]] = []

    feeds_to_fetch = (
        {source: RSS_FEEDS[source]} if source and source in RSS_FEEDS
        else RSS_FEEDS
    )

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for feed_id, feed_info in feeds_to_fetch.items():
            try:
                resp = await client.get(feed_info["url"], headers={"User-Agent": "PetroSim/1.0"})
                if resp.status_code == 200:
                    items = _parse_rss(resp.text, feed_id, feed_info["name"])
                    all_items.extend(items)
            except (httpx.HTTPError, httpx.TimeoutException):
                continue

    # Sort by pub_date descending (newest first)
    def sort_key(item: dict) -> datetime:
        try:
            return parsedate_to_datetime(item.get("pub_date", ""))
        except (ValueError, TypeError):
            return datetime.min

    all_items.sort(key=sort_key, reverse=True)

    return {
        "items": all_items[:limit],
        "sources": [
            {"id": k, "name": v["name"], "name_fr": v["name_fr"], "lang": v["lang"]}
            for k, v in RSS_FEEDS.items()
        ],
    }


@router.get("/sources")
async def list_sources():
    """List available news sources."""
    return [
        {"id": k, "name": v["name"], "name_fr": v["name_fr"], "lang": v["lang"], "url": v["url"]}
        for k, v in RSS_FEEDS.items()
    ]

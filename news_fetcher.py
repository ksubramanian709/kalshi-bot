"""
Simple news headline fetcher using RSS feeds.
No API key required.
"""
import requests
import feedparser

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]


def fetch_headlines(limit_per_feed: int = 10) -> list[str]:
    """
    Fetch latest headlines from RSS feeds.
    Returns a flat list of headline strings.
    """
    headlines = []
    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            for entry in parsed.entries[:limit_per_feed]:
                title = entry.get("title", "").strip()
                if title:
                    headlines.append(title)
        except Exception:
            pass
    return headlines

"""Free news headline sources for one company: Google News RSS and Yahoo Finance (via yfinance).

Fetching is best-effort: a source that fails returns no headlines and logs a warning, so one
broken feed never stops the job. Parsing is split from fetching so it can be tested offline.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; VynzoNews/1.0)"
TIMEOUT_S = 12
PER_SOURCE = 10

_SUFFIXES = re.compile(r"\s+(limited|ltd\.?|corporation|corp\.?|company|co\.?)$", re.IGNORECASE)


@dataclass(frozen=True)
class Headline:
    source: str  # google_news | yahoo_finance
    title: str
    url: str | None
    publisher: str | None
    published: datetime | None  # UTC

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "published": self.published.isoformat() if self.published else None,
        }


def _clean(text: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def safe_url(url: str | None) -> str | None:
    """Keep only http(s) links: a feed must never hand the web app a javascript: URL."""
    url = (url or "").strip()
    return url if url.lower().startswith(("https://", "http://")) else None


def short_name(company_name: str | None) -> str | None:
    """'Adani Enterprises Limited' -> 'Adani Enterprises' (better news search terms)."""
    if not company_name:
        return None
    name = company_name.strip()
    for _ in range(2):
        name = _SUFFIXES.sub("", name).strip(" ,.")
    return name or None


def google_news_url(symbol: str, company_name: str | None) -> str:
    name = short_name(company_name)
    if not name:
        q = f"{symbol} share NSE"
    elif len(symbol) < 3:  # a 2-letter symbol ("LT") matches unrelated stories
        q = f'"{name}" share'
    else:
        q = f'"{name}" OR {symbol} share'
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": f"{q} when:7d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    )


def parse_google_rss(raw: bytes, limit: int = PER_SOURCE) -> list[Headline]:
    root = ET.fromstring(raw)  # noqa: S314 - Google's feed over HTTPS; no DTDs or entities used
    out: list[Headline] = []
    for item in root.findall("./channel/item")[:limit]:
        title = _clean(item.findtext("title"))
        publisher = _clean(item.findtext("source")) or None
        # Google appends " - Publisher" to every title; keep the headline itself.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].rstrip()
        published = None
        if pub := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(pub).astimezone(UTC)
            except (TypeError, ValueError):
                published = None
        if title:
            out.append(
                Headline(
                    "google_news", title, safe_url(item.findtext("link")), publisher, published
                )
            )
    return out


def _yahoo_time(content: dict[str, Any], item: dict[str, Any]) -> datetime | None:
    if isinstance(pub := content.get("pubDate"), str):
        try:
            return datetime.fromisoformat(pub.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    if isinstance(ts := item.get("providerPublishTime"), int | float):
        return datetime.fromtimestamp(ts, UTC)
    return None


def parse_yahoo_news(items: list[dict[str, Any]], limit: int = PER_SOURCE) -> list[Headline]:
    """yfinance `Ticker.news` items; newer versions nest the fields under 'content'."""
    out: list[Headline] = []
    for item in items[:limit]:
        content = item["content"] if isinstance(item.get("content"), dict) else item
        title = _clean(content.get("title") or item.get("title"))
        link = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        url = link.get("url") if isinstance(link, dict) else None
        provider = content.get("provider")
        publisher = provider.get("displayName") if isinstance(provider, dict) else None
        publisher = publisher or item.get("publisher")
        if title:
            out.append(
                Headline(
                    "yahoo_finance",
                    title,
                    safe_url(url or item.get("link")),
                    publisher,
                    _yahoo_time(content, item),
                )
            )
    return out


def _get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})  # noqa: S310
    with urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https URL above
        return resp.read()


def fetch_headlines(symbol: str, exchange: str, company_name: str | None) -> list[Headline]:
    """Headlines from every source; a failing source contributes nothing."""
    out: list[Headline] = []
    try:
        out += parse_google_rss(_get(google_news_url(symbol, company_name)))
    except Exception as exc:  # noqa: BLE001 - best-effort source
        log.warning("google news failed for %s: %s", symbol, exc)
    try:
        import yfinance as yf

        ticker = f"{symbol}{'.NS' if exchange == 'NSE' else '.BO'}"
        out += parse_yahoo_news(yf.Ticker(ticker).news or [])
    except Exception as exc:  # noqa: BLE001 - best-effort source
        log.warning("yahoo news failed for %s: %s", symbol, exc)
    return out

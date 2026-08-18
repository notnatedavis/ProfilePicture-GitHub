#   src/pinterest_api.py

# --- Imports ---
import re
import time
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import logging_config

logger = logging.getLogger(__name__)

# --- in-memory cache for RSS data ---
_cache = {}
CACHE_TTL = 120  # 2 min in seconds

# --- backoff helpers ---
_retry_timers = {}
BACKOFF_BASE = 5 # seconds
BACKOFF_MAX = 60 # seconds

# --- helper functions ---
def _get_cached(key) :
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() - entry["timestamp"] > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return entry["data"]

def _set_cache(key, data) :
    _cache[key] = {"data": data, "timestamp": time.time()}

def _should_retry(key) :
    next_time = _retry_timers.get(key, 0)
    return time.time() >= next_time

def _record_failure(key) :
    prev = _retry_timers.get(key, 0)
    delay = min((time.time() - prev) * 2 if prev else BACKOFF_BASE, BACKOFF_MAX)
    _retry_timers[key] = time.time() + delay

def _reset_backoff(key) :
    _retry_timers.pop(key, None)

def parse_board_url(board_url) :
    # parse Pinterest board URL into username and board name
    try :
        parts = urlparse(board_url).path.strip("/").split("/")
        if len(parts) >= 2 :
            return {"username": parts[0], "boardName": parts[1]}
    except Exception :
        pass
    return None

def _extract_image_urls(description_text) :
    # extract all image src URLs from an RSS item description
    if not description_text :
        return []
    return re.findall(r'<img[^>]+src="([^"]+)"', description_text, re.IGNORECASE)

def get_random_pin_image(pin_images) :
    # return a random pin image URL from a list
    import random
    return random.choice(pin_images)

# --- main function ---
def fetch_board_data(board_url) :
    # fetch public Pinterest board data via RSS feed and return pin images
    parsed = parse_board_url(board_url)
    if not parsed :
        raise ValueError(
            "Invalid Pinterest board URL. Expected format: "
            "https://www.pinterest.com/username/board-name/"
        )

    username, board_name = parsed["username"], parsed["boardName"]
    cache_key = f"{username}/{board_name}"

    cached = _get_cached(cache_key)
    if cached :
        logger.debug(logging_config.label_value("Using cached data for", cache_key))
        return cached

    if not _should_retry(cache_key) :
        if cached :
            logger.debug(logging_config.block(f"Backoff active for {cache_key}, serving stale cache"))
            return cached
        logger.debug(logging_config.block(f"Backoff active for {cache_key}, no cache – throwing"))
        raise RuntimeError("Too many requests – cooling down")

    rss_url = f"https://www.pinterest.com/{username}/{board_name}.rss"
    logger.debug(logging_config.label_value("Fetching RSS feed from", rss_url))

    try :
        resp = requests.get(rss_url, timeout=10)
        resp.raise_for_status()
        xml_text = resp.text
    except requests.RequestException as err :
        logger.error(logging_config.label_value("Failed to fetch RSS feed", err))
        _record_failure(cache_key)
        if cached :
            logger.debug(logging_config.block("Serving stale cache after fetch error"))
            return cached
        raise RuntimeError(f"Unable to load board RSS feed: {err}")

    try :
        root = ET.fromstring(xml_text)
    except ET.ParseError as err :
        logger.error(logging_config.label_value("XML parsing failed", err))
        _record_failure(cache_key)
        if cached :
            return cached
        raise RuntimeError(f"RSS feed could not be parsed: {err}")

    channel_title = root.findtext("channel/title", default=board_name).strip()
    items = root.findall(".//item")
    logger.debug(logging_config.label_value("Found items in RSS feed", len(items)))
    if not items :
        _record_failure(cache_key)
        if cached :
            return cached
        raise RuntimeError("The board appears to be empty or not public.")

    all_images = []
    for item in items :
        desc_elem = item.find("description")
        if desc_elem is not None :
            all_images.extend(_extract_image_urls(desc_elem.text))

    pin_images = list(dict.fromkeys(
        url for url in all_images if "pinimg.com" in url
    ))

    logger.debug(logging_config.label_value("Total unique Pinterest images found", len(pin_images)))
    if not pin_images :
        _record_failure(cache_key)
        if cached:
            return cached
        raise RuntimeError("No pin images found in the RSS feed. The board may be empty or private.")

    result = {"title": channel_title, "pinImages": pin_images}
    _set_cache(cache_key, result)
    _reset_backoff(cache_key)
    return result
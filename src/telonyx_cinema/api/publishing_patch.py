import html
import re
from urllib.parse import unquote

import httpx

TRUSTED_IMAGE_DOMAINS = {
    "starwars.com", "lucasfilm.com", "disney.com", "disneyplus.com",
    "imdb.com", "media-amazon.com", "m.media-amazon.com",
    "tmdb.org", "themoviedb.org", "image.tmdb.org",
    "rottentomatoes.com", "fandango.com", "cinematerial.com", "impawards.com",
    "movieposters.com", "warnerbros.com", "universalpictures.com",
    "paramountpictures.com", "sonypictures.com", "20thcenturystudios.com",
}

EXTRA_BLOCKED = {
    "rule34", "porn", "nsfw", "ai generated", "midjourney", "stable diffusion",
    "wallpaper", "wallpapers", "deviantart", "cosplay", "cosplayer",
    "costume", "fanart", "fan art", "fan-art", "fandom", "fanpop",
    "tumblr", "aminoapps", "pinterest", "redbubble", "etsy", "shirt",
    "t-shirt", "hoodie", "meme", "sticker", "clipart", "christmas",
}


def _clean(value: str) -> str:
    value = html.unescape(unquote(value or "")).lower()
    value = re.sub(r"[^a-z0-9а-яіїєґ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _title_tokens(p, movie_title: str) -> list[str]:
    if hasattr(p, "movie_title_tokens"):
        return p.movie_title_tokens(movie_title)
    tokens = re.findall(r"[a-zA-Z0-9а-яА-ЯіїІЇєЄґҐ]+", movie_title or "")
    stop = getattr(p, "TITLE_TOKEN_STOP_WORDS", set())
    result = []
    for token in tokens:
        token = token.lower()
        if len(token) >= 3 and token not in stop and token not in result:
            result.append(token)
    return result


def _synonyms(p, movie_title: str) -> set[str]:
    low = (movie_title or "").lower()
    result = set(_title_tokens(p, movie_title))
    squashed = re.sub(r"[^a-z0-9]+", "", low)
    if squashed:
        result.add(squashed)
    if "star wars" in low or "mandalorian" in low or "grogu" in low:
        result.update({"starwars", "star", "wars", "mandalorian", "grogu", "lucasfilm", "disney"})
    return result


def apply(p):
    p.IMAGE_BLOCKLIST = set(getattr(p, "IMAGE_BLOCKLIST", set())) | EXTRA_BLOCKED
    p.TRUSTED_IMAGE_DOMAINS = TRUSTED_IMAGE_DOMAINS

    def is_blocked_image_candidate(url: str, context: str = "") -> bool:
        haystack = f"{url} {context}".lower()
        return any(bad in haystack for bad in p.IMAGE_BLOCKLIST)

    def is_trusted_image_context(url: str, context: str = "") -> bool:
        haystack = f"{url} {context}".lower()
        return any(domain in haystack for domain in TRUSTED_IMAGE_DOMAINS)

    def movie_synonyms(movie_title: str) -> set[str]:
        return _synonyms(p, movie_title)

    def image_relevance_score(url: str, context: str, movie_title: str) -> int:
        if is_blocked_image_candidate(url, context):
            return -100
        haystack = _clean(f"{url} {context}")
        tokens = _title_tokens(p, movie_title)
        synonyms = movie_synonyms(movie_title)
        score = 0
        hits = 0
        for token in tokens:
            if re.search(rf"\b{re.escape(token)}\b", haystack) or token in haystack:
                hits += 1
                score += 4
        for token in synonyms - set(tokens):
            if token and token in haystack:
                score += 2
        if is_trusted_image_context(url, context):
            score += 5
        if any(word in haystack for word in ["official", "press", "still", "trailer", "poster", "backdrop", "promo", "image", "photo"]):
            score += 2
        if any(word in haystack for word in ["imdb", "tmdb", "themoviedb", "starwars", "lucasfilm", "disney"]):
            score += 3
        # Важно: не принимаем CDN-ссылку без контекста, если в ней вообще нет названия фильма.
        if len(tokens) >= 2 and hits == 0:
            return -10
        # Но не режем нормальные постеры/стиллы с одним точным токеном, если источник официальный/доверенный.
        if len(tokens) >= 3 and hits == 1 and not is_trusted_image_context(url, context):
            return -5
        return score

    def is_relevant_image_candidate(url: str, context: str, movie_title: str) -> bool:
        return image_relevance_score(url, context, movie_title) >= 4

    def add_candidate(candidates: list[dict[str, str]], url: str | None, movie_title: str, context: str = "", source: str = "") -> None:
        if not url:
            return
        url = html.unescape(unquote(url)).strip()
        if not url.startswith(("http://", "https://")):
            return
        lowered = url.lower()
        if any(bad in lowered for bad in [".svg", "favicon", "logo", "sprite", "data:image"]):
            return
        score = image_relevance_score(url, context, movie_title)
        if score < 4:
            return
        if any(item["url"] == url for item in candidates):
            return
        candidates.append({"url": url, "context": context, "source": source, "score": str(score)})

    async def bing_image_candidates(query: str, movie_title: str, limit: int = 12) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
                page = (await client.get("https://www.bing.com/images/search", params={"q": query, "form": "HDRSC2", "first": "1"})).text
            for block in re.findall(r"m=\"(.*?)\"", page):
                unescaped = html.unescape(block)
                murl = re.search(r'"murl":"(.*?)"', unescaped)
                title = re.search(r'"t":"(.*?)"', unescaped)
                purl = re.search(r'"purl":"(.*?)"', unescaped)
                context = " ".join(x.group(1) for x in [title, purl] if x)
                if murl:
                    add_candidate(candidates, murl.group(1).encode("utf-8").decode("unicode_escape"), movie_title, context=context, source="bing")
                if len(candidates) >= limit:
                    break
        except Exception:
            return []
        return candidates

    async def search_image_candidates(query: str, movie_title: str) -> dict:
        candidates: list[dict[str, str]] = []
        sources = {"duckduckgo": 0, "bing": 0, "wikimedia": 0}
        for source_name, loader in [
            ("duckduckgo", p.duckduckgo_image_candidates),
            ("bing", bing_image_candidates),
            ("wikimedia", p.wikimedia_image_candidates),
        ]:
            if len(candidates) >= p.IMAGE_COUNT * 2:
                break
            items = await loader(query, movie_title)
            sources[source_name] += len(items)
            for item in items:
                add_candidate(candidates, item["url"], movie_title, item.get("context", ""), item.get("source", source_name))
        candidates.sort(key=lambda item: int(item.get("score", "0")), reverse=True)
        return {"query": query, "candidates": candidates, "sources": sources}

    def build_search_queries_from_post(movie_title: str, movie_year: str, telegram_text_uk: str, gemini_queries: list[str]) -> list[str]:
        base = movie_title.strip()
        year = str(movie_year).strip()
        result = [
            f'"{base}" {year} official movie still',
            f'"{base}" {year} official poster',
            f'"{base}" {year} official trailer still',
            f'"{base}" {year} cast premiere',
            f'"{base}" {year} press image',
            f'"{base}" imdb still',
            f'"{base}" tmdb backdrop',
        ]
        if "mandalorian" in base.lower() or "grogu" in base.lower():
            result = [
                '"The Mandalorian and Grogu" official trailer still',
                '"The Mandalorian and Grogu" official poster',
                '"The Mandalorian and Grogu" Lucasfilm press image',
                '"The Mandalorian and Grogu" StarWars.com image',
                '"The Mandalorian and Grogu" Disney still',
                '"The Mandalorian and Grogu" Grogu still',
                '"The Mandalorian and Grogu" Pedro Pascal still',
            ] + result
        for query in gemini_queries or []:
            query = str(query).strip()
            if query and not is_blocked_image_candidate(query):
                result.append(query)
        for phrase in p.extract_post_search_phrases(telegram_text_uk, movie_title, movie_year):
            if not is_blocked_image_candidate(phrase):
                result.extend([f'"{base}" "{phrase}" movie still', f'"{base}" "{phrase}" press image'])
        unique = []
        seen = set()
        for query in result:
            query = re.sub(r"\s+", " ", query).strip()
            key = query.lower()
            if query and key not in seen and not is_blocked_image_candidate(query):
                seen.add(key)
                unique.append(query)
        return unique[:18]

    p.is_blocked_image_candidate = is_blocked_image_candidate
    p.is_relevant_image_candidate = is_relevant_image_candidate
    p.image_relevance_score = image_relevance_score
    p.movie_synonyms = movie_synonyms
    p.add_candidate = add_candidate
    p.bing_image_candidates = bing_image_candidates
    p.search_image_candidates = search_image_candidates
    p.build_search_queries_from_post = build_search_queries_from_post
    return p

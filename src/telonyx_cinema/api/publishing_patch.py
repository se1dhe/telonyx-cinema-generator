import html
import json
import os
import re
from urllib.parse import unquote, urljoin

import httpx

TRUSTED_IMAGE_DOMAINS = {
    "image.tmdb.org", "tmdb.org", "themoviedb.org",
    "starwars.com", "lucasfilm.com", "disney.com", "disneyplus.com",
    "imdb.com", "media-amazon.com", "m.media-amazon.com",
    "rottentomatoes.com", "fandango.com", "cinematerial.com", "impawards.com",
    "movieposters.com", "warnerbros.com", "universalpictures.com",
    "paramountpictures.com", "sonypictures.com", "20thcenturystudios.com",
}

EXTRA_BLOCKED = {
    "rule34", "porn", "nsfw", "ai generated", "midjourney", "stable diffusion",
    "deviantart", "cosplay", "cosplayer", "costume", "fanart", "fan art",
    "fan-art", "fandom", "fanpop", "tumblr", "aminoapps", "pinterest",
    "redbubble", "etsy", "shirt", "t-shirt", "hoodie", "meme", "sticker",
    "clipart", "christmas", "tattoo", "sleeve", "ink", "mandala",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"


def _clean(value: str) -> str:
    value = html.unescape(unquote(value or "")).lower()
    value = re.sub(r"[^a-z0-9а-яіїєґ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _title_tokens(p, movie_title: str) -> list[str]:
    stop = getattr(p, "TITLE_TOKEN_STOP_WORDS", set())
    tokens = re.findall(r"[a-zA-Z0-9а-яА-ЯіїІЇєЄґҐ]+", movie_title or "")
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


def _year_matches(movie_year: str, date_value: str | None) -> bool:
    year = str(movie_year or "").strip()
    if not year or not date_value:
        return True
    return str(date_value).startswith(year)


def apply(p):
    p.IMAGE_BLOCKLIST = set(getattr(p, "IMAGE_BLOCKLIST", set())) | EXTRA_BLOCKED
    p.TRUSTED_IMAGE_DOMAINS = TRUSTED_IMAGE_DOMAINS

    def is_blocked_image_candidate(url: str, context: str = "") -> bool:
        haystack = f"{url} {context}".lower()
        return any(bad in haystack for bad in p.IMAGE_BLOCKLIST)

    def trusted_domain_score(url: str, context: str = "") -> int:
        haystack = f"{url} {context}".lower()
        return 10 if any(domain in haystack for domain in TRUSTED_IMAGE_DOMAINS) else 0

    def movie_synonyms(movie_title: str) -> set[str]:
        return _synonyms(p, movie_title)

    def image_relevance_score(url: str, context: str, movie_title: str) -> int:
        if is_blocked_image_candidate(url, context):
            return -100
        haystack = _clean(f"{url} {context}")
        tokens = _title_tokens(p, movie_title)
        synonyms = movie_synonyms(movie_title)
        score = trusted_domain_score(url, context)
        hits = 0
        for token in tokens:
            if token and (re.search(rf"\b{re.escape(token)}\b", haystack) or token in haystack):
                hits += 1
                score += 5
        for token in synonyms - set(tokens):
            if token and token in haystack:
                score += 3
        if any(word in haystack for word in ["official", "press", "still", "trailer", "poster", "backdrop", "promo", "image", "photo", "exclusive"]):
            score += 3
        if any(word in haystack for word in ["imdb", "tmdb", "themoviedb", "starwars", "lucasfilm", "disney", "media amazon"]):
            score += 5
        if trusted_domain_score(url, context) and (hits >= 1 or any(x in haystack for x in synonyms)):
            return max(score, 10)
        if len(tokens) >= 2 and hits == 0 and not any(x in haystack for x in synonyms):
            return -10
        if len(tokens) >= 3 and hits == 1 and not any(x in haystack for x in ["starwars", "lucasfilm", "disney", "imdb", "tmdb", "themoviedb"]):
            return -5
        return score

    def add_candidate(candidates: list[dict[str, str]], url: str | None, movie_title: str, context: str = "", source: str = "", score_override: int | None = None) -> None:
        if not url:
            return
        url = html.unescape(unquote(url)).strip()
        if not url.startswith(("http://", "https://")):
            return
        lowered = url.lower()
        if any(bad in lowered for bad in [".svg", "favicon", "logo", "sprite", "data:image", ".gif"]):
            return
        score = score_override if score_override is not None else image_relevance_score(url, context, movie_title)
        if score < 4:
            return
        if any(item["url"] == url for item in candidates):
            return
        candidates.append({"url": url, "context": context, "source": source, "score": str(score)})

    async def tmdb_image_candidates(movie_title: str, movie_year: str, limit: int = 12) -> tuple[list[dict[str, str]], dict[str, object]]:
        """Основной стабильный источник: TMDb poster/backdrop по названию фильма."""
        token = os.getenv("TMDB_API_KEY", "").strip() or os.getenv("TMDB_BEARER_TOKEN", "").strip()
        debug: dict[str, object] = {"enabled": bool(token), "found": 0, "movie_id": None, "error": None}
        if not token:
            debug["error"] = "TMDB_API_KEY/TMDB_BEARER_TOKEN is not configured"
            return [], debug
        headers = dict(HEADERS)
        # Поддерживаем оба варианта: v4 Bearer token и v3 api_key.
        use_bearer = len(token) > 40 or token.startswith("ey")
        if use_bearer:
            headers["Authorization"] = f"Bearer {token}"
        params = {"query": movie_title, "include_adult": "false", "language": "en-US"}
        if str(movie_year or "").strip():
            params["year"] = str(movie_year).strip()
        if not use_bearer:
            params["api_key"] = token
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
                search = await client.get("https://api.themoviedb.org/3/search/movie", params=params)
                search.raise_for_status()
                search_data = search.json()
                results = search_data.get("results") or []
                if not results and params.get("year"):
                    params.pop("year", None)
                    search = await client.get("https://api.themoviedb.org/3/search/movie", params=params)
                    search.raise_for_status()
                    results = (search.json()).get("results") or []
                if not results:
                    debug["error"] = "TMDb movie not found"
                    return [], debug
                tokens = set(_title_tokens(p, movie_title))
                def rank(item: dict) -> tuple[int, float]:
                    title = _clean(" ".join([str(item.get("title") or ""), str(item.get("original_title") or "")]))
                    hit_count = sum(1 for token in tokens if token in title)
                    year_bonus = 5 if _year_matches(movie_year, item.get("release_date")) else 0
                    return (hit_count * 10 + year_bonus, float(item.get("popularity") or 0))
                movie = sorted(results, key=rank, reverse=True)[0]
                movie_id = movie.get("id")
                debug["movie_id"] = movie_id
                context = f'{movie.get("title", movie_title)} {movie.get("original_title", "")} {movie.get("release_date", "")} tmdb themoviedb'
                candidates: list[dict[str, str]] = []
                for key, score in [("backdrop_path", 50), ("poster_path", 45)]:
                    path = movie.get(key)
                    if path:
                        add_candidate(candidates, f"{TMDB_IMAGE_BASE}{path}", movie_title, context=context, source="tmdb-search", score_override=score)
                params_images = {"language": "en,null"}
                if not use_bearer:
                    params_images["api_key"] = token
                images_response = await client.get(f"https://api.themoviedb.org/3/movie/{movie_id}/images", params=params_images)
                images_response.raise_for_status()
                images = images_response.json()
                for item in (images.get("backdrops") or [])[:8]:
                    path = item.get("file_path")
                    if path:
                        add_candidate(candidates, f"{TMDB_IMAGE_BASE}{path}", movie_title, context=context, source="tmdb-backdrop", score_override=48)
                for item in (images.get("posters") or [])[:6]:
                    path = item.get("file_path")
                    if path:
                        add_candidate(candidates, f"{TMDB_IMAGE_BASE}{path}", movie_title, context=context, source="tmdb-poster", score_override=44)
                debug["found"] = len(candidates)
                return candidates[:limit], debug
        except Exception as exc:
            debug["error"] = str(exc)
            return [], debug

    async def ddg_web_page_candidates(query: str, movie_title: str, limit: int = 12) -> list[dict[str, str]]:
        pages: list[dict[str, str]] = []
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
                html_page = (await client.get("https://duckduckgo.com/html/", params={"q": query})).text
                links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_page, flags=re.I | re.S)
                for href, title_html in links[:limit]:
                    title = re.sub(r"<[^>]+>", " ", html.unescape(title_html))
                    href = html.unescape(unquote(href))
                    real = re.search(r"uddg=([^&]+)", href)
                    if real:
                        href = unquote(real.group(1))
                    if not href.startswith("http") or is_blocked_image_candidate(href, title):
                        continue
                    pages.append({"url": href, "context": title, "source": "duckduckgo-web"})
        except Exception:
            return []
        return pages

    async def og_image_candidates_from_pages(query: str, movie_title: str, limit: int = 12) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        pages = await ddg_web_page_candidates(query, movie_title, limit=limit)
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
                for page in pages:
                    if len(result) >= limit:
                        break
                    try:
                        response = await client.get(page["url"])
                        ctype = response.headers.get("content-type", "")
                        if "text/html" not in ctype and "application/xhtml" not in ctype:
                            continue
                        body = response.text[:700_000]
                    except Exception:
                        continue
                    images = []
                    patterns = [
                        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
                    ]
                    for pattern in patterns:
                        images.extend(re.findall(pattern, body, flags=re.I))
                    context = f'{page.get("context", "")} {page.get("url", "")}'
                    for image_url in images:
                        image_url = urljoin(page["url"], html.unescape(image_url))
                        add_candidate(result, image_url, movie_title, context=context, source="web-og-image")
        except Exception:
            return result
        return result

    async def bing_image_candidates(query: str, movie_title: str, limit: int = 20) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
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
        sources = {"web-og-image": 0, "duckduckgo": 0, "bing": 0, "wikimedia": 0}
        loaders = [
            ("web-og-image", og_image_candidates_from_pages),
            ("duckduckgo", p.duckduckgo_image_candidates),
            ("bing", bing_image_candidates),
            ("wikimedia", p.wikimedia_image_candidates),
        ]
        for source_name, loader in loaders:
            if len(candidates) >= p.IMAGE_COUNT * 3:
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
            f'"{base}" {year} press image',
            f'"{base}" {year} imdb still',
            f'"{base}" {year} tmdb backdrop',
        ]
        if "mandalorian" in base.lower() or "grogu" in base.lower():
            result = [
                'site:starwars.com "The Mandalorian and Grogu" image',
                'site:starwars.com "The Mandalorian and Grogu" trailer',
                'site:lucasfilm.com "The Mandalorian and Grogu"',
                'site:disney.com "The Mandalorian and Grogu"',
                '"The Mandalorian and Grogu" official trailer still',
                '"The Mandalorian and Grogu" official poster',
                '"The Mandalorian and Grogu" Lucasfilm press image',
                '"The Mandalorian and Grogu" Grogu still',
            ] + result
        for query in gemini_queries or []:
            query = str(query).strip()
            if query and not is_blocked_image_candidate(query):
                result.append(query)
        unique = []
        seen = set()
        for query in result:
            query = re.sub(r"\s+", " ", query).strip()
            key = query.lower()
            if query and key not in seen and not is_blocked_image_candidate(query):
                seen.add(key)
                unique.append(query)
        return unique[:16]

    async def create_internet_images(package_id: str, movie_title: str, movie_year: str, telegram_text_uk: str, queries: list[str]):
        images_dir = p.package_dir(package_id) / "images"
        raw_dir = images_dir / "raw"
        images_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        search_queries = build_search_queries_from_post(movie_title, movie_year, telegram_text_uk, queries)
        found: list[dict[str, str]] = []
        debug = {
            "queries": [],
            "search_queries": search_queries,
            "title_tokens": _title_tokens(p, movie_title),
            "tmdb": None,
            "downloaded": 0,
            "fallback": 0,
            "blocked_keywords": sorted(p.IMAGE_BLOCKLIST),
            "note": "TMDb is the primary provider. Fallback cards are disabled for Telegram preview.",
        }
        tmdb_items, tmdb_debug = await tmdb_image_candidates(movie_title, movie_year, limit=16)
        debug["tmdb"] = tmdb_debug
        for item in tmdb_items:
            if not any(x["url"] == item["url"] for x in found):
                found.append(item)
        if len(found) < p.IMAGE_COUNT:
            for query in search_queries:
                result = await search_image_candidates(query, movie_title)
                debug["queries"].append({"query": query, "found": len(result["candidates"]), "sources": result["sources"]})
                for item in result["candidates"]:
                    if not any(x["url"] == item["url"] for x in found):
                        found.append(item)
                if len(found) >= p.IMAGE_COUNT * 4:
                    break
        images = []
        used_urls = []
        cursor = 0
        for index in range(1, p.IMAGE_COUNT + 1):
            filename = f"{index:02d}-internet.jpg"
            raw_path = raw_dir / filename
            target = images_dir / filename
            ok = False
            source_url = None
            source_name = None
            source_score = None
            while cursor < len(found) and not ok:
                candidate = found[cursor]
                cursor += 1
                if candidate["url"] in used_urls:
                    continue
                if await p.download_image(candidate["url"], raw_path):
                    try:
                        p.style_internet_image(raw_path, target, index)
                        source_url = candidate["url"]
                        source_name = candidate.get("source")
                        source_score = candidate.get("score")
                        used_urls.append(candidate["url"])
                        ok = True
                        debug["downloaded"] += 1
                    except Exception:
                        ok = False
            if ok:
                images.append({
                    "id": p.uuid.uuid4().hex,
                    "kind": "internet_image",
                    "sort_order": index,
                    "source": source_name,
                    "source_url": source_url,
                    "score": source_score,
                    "alt_text_uk": f"{movie_title} — зображення {index}",
                    "local_path": str(target),
                    "url": f"/api/publish-packages/{package_id}/images/{filename}",
                })
        debug["total_relevant_candidates"] = len(found)
        debug["used_urls"] = used_urls
        debug["final_image_count"] = len(images)
        debug["real_image_count"] = len(images)
        if len(images) < p.MIN_IMAGE_COUNT:
            debug["error"] = "Not enough real movie images found. Configure TMDB_API_KEY for stable movie posters/backdrops."
        return images, debug

    async def generate_package_task(package_id: str) -> None:
        package = p.read_json(p.package_dir(package_id) / "package.json")
        movie_title = package["movie_title"]
        movie_year = package["movie_year"]
        try:
            p.update_package(package_id, {"status": "generating", "message": "Генерирую Telegram-caption через Gemini"})
            content = await p.generate_with_gemini(movie_title, movie_year)
            p.update_package(package_id, {"message": "Ищу реальные 2-3 картинки фильма через TMDb и интернет"})
            images, image_debug = await create_internet_images(package_id, movie_title, movie_year, content.get("telegram_text_uk", ""), content.get("image_queries", []))
            status = "ready" if len(images) >= p.MIN_IMAGE_COUNT else "failed"
            message = "Контент-пакет готов к предпросмотру" if status == "ready" else "Не удалось найти минимум 2 реальные картинки фильма. Добавь TMDB_API_KEY в Railway или попробуй другое название."
            p.update_package(package_id, {
                "status": status,
                "message": message,
                "telegram_text_uk": content.get("telegram_text_uk", ""),
                "tiktok_title": content.get("tiktok_title", ""),
                "tiktok_description": content.get("tiktok_description", ""),
                "tiktok_hashtags": content.get("tiktok_hashtags", []),
                "youtube_title": content.get("youtube_title", ""),
                "youtube_description": content.get("youtube_description", ""),
                "youtube_hashtags": content.get("youtube_hashtags", []),
                "source_links": content.get("source_links", []),
                "gemini_image_queries": content.get("image_queries", []),
                "image_queries": image_debug.get("search_queries", content.get("image_queries", [])),
                "images": images,
                "image_debug": image_debug,
                "generator_meta": {
                    "generated_by": content.get("generated_by"),
                    "gemini_error": content.get("gemini_error"),
                    "brand_style": p.BRAND_STYLE,
                    "image_source": "tmdb_first_real_movie_images_no_fallback_cards",
                    "telegram_mode": "single_album_post_caption",
                },
            })
        except Exception as exc:
            p.update_package(package_id, {"status": "failed", "message": str(exc), "error_message": str(exc)})

    p.is_blocked_image_candidate = is_blocked_image_candidate
    p.image_relevance_score = image_relevance_score
    p.movie_synonyms = movie_synonyms
    p.add_candidate = add_candidate
    p.tmdb_image_candidates = tmdb_image_candidates
    p.bing_image_candidates = bing_image_candidates
    p.search_image_candidates = search_image_candidates
    p.build_search_queries_from_post = build_search_queries_from_post
    p.create_internet_images = create_internet_images
    p.generate_package_task = generate_package_task
    return p

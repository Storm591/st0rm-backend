import os
import re
from urllib.parse import urljoin
from flask import Flask, jsonify, request
from flask_cors import CORS
import cloudscraper
from bs4 import BeautifulSoup, Tag

app = Flask(__name__)
# Enable CORS so your frontend can talk to this backend safely
CORS(app)

# Create cloudscraper instance to bypass basic Cloudflare protection
scraper = cloudscraper.create_scraper(
    browser={
        "browser": "chrome",
        "platform": "windows",
        "desktop": True,
    }
)


def extract_poster(post: Tag, base_url: str) -> str:
    """
    Checks lazy-loading attributes BEFORE 'src' and ignores base64 placeholders.
    """
    img_tag = post.find("img")
    if not img_tag:
        return ""

    # Check lazy-load attributes first; fallback to standard 'src' last
    for attr in ["data-src", "data-lazy-src", "data-original", "src"]:
        val = img_tag.get(attr)
        if val and not val.strip().startswith("data:image/"):
            return urljoin(base_url, val.strip())

    # Fallback to srcset if present
    for srcset_attr in ["data-srcset", "srcset"]:
        srcset = img_tag.get(srcset_attr, "").strip()
        if srcset:
            first_url = srcset.split(",")[0].strip().split(" ")[0]
            if first_url and not first_url.startswith("data:image/"):
                return urljoin(base_url, first_url)

    return ""


def extract_title_and_link(post: Tag, base_url: str):
    """
    Finds the valid link and extracts the human-readable title even when
    the first <a> tag only wraps an <img> thumbnail.
    """
    # 1. Try finding a dedicated title element first (figcaption, headings, or p)
    title_el = post.find(["figcaption", "h1", "h2", "h3", "h4", "p"])
    link_tag = None
    title = ""

    if title_el:
        link_tag = title_el.find("a", href=True) or title_el.find_parent("a", href=True)
        title = title_el.get_text(" ", strip=True)

    # 2. Fallback: Check all <a> tags inside the post container
    all_links = post.find_all("a", href=True) if post.name != "a" else [post]
    if not link_tag and all_links:
        # Prefer an <a> tag that actually contains text
        for a in all_links:
            text = a.get_text(" ", strip=True)
            if text:
                link_tag = a
                title = text
                break
        # Otherwise use the first <a> tag
        if not link_tag:
            link_tag = all_links[0]

    if not link_tag or not link_tag.get("href"):
        return None, None

    raw_href = link_tag["href"].strip()
    if not raw_href or raw_href.startswith(("#", "javascript:")):
        return None, None

    link = urljoin(base_url, raw_href)

    # 3. Fallback chain for title if text was empty (e.g. image-only link)
    if not title:
        img = post.find("img")
        title = (
            link_tag.get("title", "").strip()
            or (img.get("alt", "").strip() if img else "")
            or post.get_text(" ", strip=True)
            or "No Title"
        )

    return title, link


def find_post_containers(soup: BeautifulSoup):
    """
    Tries multiple CSS selectors used by grid/archive themes, then falls back
    to heuristic parent discovery if classes were renamed.
    """
    candidate_selectors = [
        "ul.recent-movies > li",
        "li.thumb",
        ".itemarchiv",
        "article",
        "li.post",
        ".post-item",
        ".movie-card",
        "[class*='item']",
        "[class*='post-']",
    ]

    for selector in candidate_selectors:
        found = soup.select(selector)
        # Ensure matched containers actually hold links and images
        valid = [el for el in found if el.find("a", href=True) and el.find("img")]
        if len(valid) >= 2:
            return valid, selector

    # Heuristic Fallback: Find all <img> tags inside or adjacent to <a> tags
    fallback_containers = []
    seen_nodes = set()
    for img in soup.find_all("img"):
        card = img.find_parent(["li", "article", "figure", "div"])
        if card and id(card) not in seen_nodes and card.find("a", href=True):
            seen_nodes.add(id(card))
            fallback_containers.append(card)

    return fallback_containers, "heuristic_fallback"


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "message": "St0rm Cinema Robot Helper is running!"
    })


@app.route("/api/scrape", methods=["GET"])
def scrape_hdhub4u():
    target_url = request.args.get("url", "https://hdhub4u.phd/")

    try:
        response = scraper.get(target_url, timeout=15)

        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Failed to access page. Status code: {response.status_code}"
            }), 500

        soup = BeautifulSoup(response.text, "html.parser")

        # Strip out navigation, header, and footer noise so fallback selectors stay clean
        for noise in soup.select("nav, header, footer, script, style"):
            noise.decompose()

        posts, matched_selector = find_post_containers(soup)

        movies = []
        seen_links = set()

        for post in posts:
            title, link = extract_title_and_link(post, target_url)
            if not link or link in seen_links:
                continue

            seen_links.add(link)
            poster = extract_poster(post, target_url)

            # Extract year from dedicated class OR fallback to regex (19xx / 20xx) in title
            year = ""
            meta_tag = post.find(class_="year") or post.find(class_="entry-date")
            if meta_tag:
                year = meta_tag.get_text(strip=True)
            else:
                year_match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
                if year_match:
                    year = year_match.group(1)

            movies.append({
                "id": f"scraped_{len(movies)}",
                "title": title,
                "link": link,
                "poster": poster,
                "year": year,
                "type": "movie"
            })

        return jsonify({
            "success": True,
            "matched_selector": matched_selector,
            "page_title": soup.title.string.strip() if soup.title and soup.title.string else "No Title",
            "count": len(movies),
            "movies": movies
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

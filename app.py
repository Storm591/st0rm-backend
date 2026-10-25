import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import cloudscraper
from bs4 import BeautifulSoup

app = Flask(__name__)
# Enable CORS so your Netlify website can talk to this backend safely
CORS(app)

# Create cloudscraper instance to bypass basic Cloudflare protection
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "message": "St0rm Cinema Robot Helper is running!"
    })

@app.route("/api/scrape", methods=["GET"])
def scrape_hdhub4u():
    # Allow passing a custom search or page URL, defaults to home domain
    target_url = request.args.get("url", "https://hdhub4u.phd/")
    
    try:
        response = scraper.get(target_url, timeout=15)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Failed to access page. Status code: {response.status_code}"
            }), 500

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # HDHub4u layout item selectors
        posts = soup.find_all('article') or soup.select('.itemarchiv') or soup.find_all('li', class_='post')
        
        movies = []
        for index, post in enumerate(posts):
            link_tag = post.find('a') if post.name != 'a' else post
            
            if link_tag and link_tag.get('href'):
                title = link_tag.get_text(strip=True) or link_tag.get('title', 'No Title')
                link = link_tag['href']
                
                # Extract poster thumbnail if available
                img_tag = post.find('img')
                poster = ""
                if img_tag:
                    poster = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('srcset', '').split(' ')[0]

                # Extract year if present in title text or post meta
                year = ""
                meta_tag = post.find(class_='year') or post.find(class_='entry-date')
                if meta_tag:
                    year = meta_tag.get_text(strip=True)

                movies.append({
                    "id": f"scraped_{index}",
                    "title": title,
                    "link": link,
                    "poster": poster,
                    "year": year,
                    "type": "movie"
                })

        return jsonify({
            "success": True,
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
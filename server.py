import os
import json
import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from urllib.parse import urlparse
import socket
import ipaddress

IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]

mcp = FastMCP("instagram-mcp")


def is_safe_url(url: str) -> bool:
    """Check if the URL is safe and not pointing to internal/private networks."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Resolve to IP to check for private ranges
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)
        return not (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast)
    except Exception:
        return False

@mcp.tool()
def scrape_website(url: str) -> str:
    """Scrape text content from a website URL."""
    if not is_safe_url(url):
        return json.dumps({"error": "URL not allowed for security reasons (private/internal range blocked)"})
    
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TangibleDataBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "head"]):
        tag.decompose()
    title = soup.find("title")
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 40]
    meta = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta.get("content", "") if meta else ""
    return json.dumps({
        "title": title.get_text(strip=True) if title else "",
        "meta_description": meta_desc,
        "headings": headings[:10],
        "paragraphs": paragraphs[:6],
        "url": url,
    }, ensure_ascii=False)


@mcp.tool()
def publish_instagram_post(caption: str) -> str:
    """
    Publish a post to Instagram using a default background image.
    caption: The full post text including hashtags.
    """
    DEFAULT_IMAGE_URL = "https://storage.googleapis.com/tangibledata-assets/post-bg.png"
    create_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media"
    resp = requests.post(
        create_url,
        data={
            "caption": caption,
            "image_url": DEFAULT_IMAGE_URL,
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        return json.dumps({"error": resp.json()})
    container_id = resp.json().get("id")

    pub_resp = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
        timeout=15,
    )
    if not pub_resp.ok:
        return json.dumps({"error": pub_resp.json()})
    return json.dumps({"success": True, "post_id": pub_resp.json().get("id")})


@mcp.tool()
def publish_instagram_post_with_image(caption: str, image_url: str) -> str:
    """
    Publish an image post to Instagram.
    caption: The full post text including hashtags.
    image_url: Public URL of the image to post (must be publicly accessible).
    """
    create_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media"
    resp = requests.post(
        create_url,
        data={
            "caption": caption,
            "image_url": image_url,
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        return json.dumps({"error": resp.json()})
    container_id = resp.json().get("id")

    pub_resp = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
        timeout=15,
    )
    if not pub_resp.ok:
        return json.dumps({"error": pub_resp.json()})
    return json.dumps({"success": True, "post_id": pub_resp.json().get("id")})


@mcp.tool()
def get_instagram_account_info() -> str:
    """Get basic info about the connected Instagram account."""
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}",
        params={
            "fields": "username,name,biography,followers_count,media_count",
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        return json.dumps({"error": resp.json()})
    return json.dumps(resp.json())


@mcp.tool()
def get_recent_posts(limit: int = 5) -> str:
    """Get the most recent Instagram posts from the account."""
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        params={
            "fields": "id,caption,timestamp,permalink,media_type",
            "limit": limit,
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        return json.dumps({"error": resp.json()})
    return json.dumps(resp.json())


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    # mcp.run(transport="streamable-http") 
    # Use uvicorn directly to ensure it listens on the correct port and host for Cloud Run
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")

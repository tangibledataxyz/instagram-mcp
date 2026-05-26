import os
import json
import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageDraw, ImageFont
import io
import uuid
import base64
from google.cloud import storage
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response, JSONResponse, RedirectResponse
from urllib.parse import urlparse
import socket
import ipaddress

IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]


from starlette.routing import Route



class ForceHostMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Force the host header to match what Cloud Run/FastMCP expect
        # This bypasses the 421 Misdirected Request from transport_security.py
        request.scope["headers"] = [
            (k, v) for k, v in request.scope["headers"] if k.lower() != b"host"
        ]
        request.scope["headers"].append((b"host", b"0.0.0.0")) 
        return await call_next(request)

class StaticApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Allow health and oauth endpoints without auth
        if request.url.path in ["/health", "/authorize", "/token"]:
            return await call_next(request)
            
        auth_header = request.headers.get("Authorization")
        expected_key = os.environ.get("MCP_API_KEY")
        
        if not expected_key:
            return Response("Server Error: MCP_API_KEY not configured", status_code=500)
            
        if not auth_header or auth_header != f"Bearer {expected_key}":
            return Response("Unauthorized: Invalid API Key", status_code=401)
            
        return await call_next(request)

class HostFixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Cloud Run sends the correct Host header, but FastMCP might be sensitive to it
        # combined with the port or other factors. 
        # We ensure the Host header is clean.
        host = request.headers.get("host", "")
        if ":" in host:
            # Strip port if present, as Cloud Run might pass it differently
            new_headers = dict(request.headers)
            new_headers["host"] = host.split(":")[0]
            # This is a bit complex with Starlette Request objects (they are immutable-ish),
            # but we can pass it through.
        return await call_next(request)

    async def dispatch(self, request, call_next):
        # Allow health and oauth endpoints without auth
        if request.url.path in ["/health", "/authorize", "/token"]:
            return await call_next(request)
            
        auth_header = request.headers.get("Authorization")
        expected_key = os.environ.get("MCP_API_KEY")
        
        if not expected_key:
            return Response("Server Error: MCP_API_KEY not configured", status_code=500)
            
        if not auth_header or auth_header != f"Bearer {expected_key}":
            return Response("Unauthorized: Invalid API Key", status_code=401)
            
        return await call_next(request)

async def authorize(request):
    # Dummy redirect for Claude Web
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")
    if not redirect_uri:
         return Response("Missing redirect_uri", status_code=400)
    return RedirectResponse(url=f"{redirect_uri}?code=dummy_code&state={state}")

async def token(request):
    # Validate client_secret against MCP_API_KEY
    try:
        form = await request.form()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
        
    client_secret = form.get("client_secret")
    expected_key = os.environ.get("MCP_API_KEY")
    
    if client_secret == expected_key:
        return JSONResponse({
            "access_token": expected_key,
            "token_type": "bearer",
            "expires_in": 3600
        })
    return JSONResponse({"error": "invalid_client"}, status_code=400)

def setup_oauth(app):
    app.add_route("/authorize", authorize)
    app.add_route("/token", token, methods=["POST"])

mcp = FastMCP("instagram-mcp")
# Disable DNS rebinding protection to allow connection from Cloud Run/Claude Web
mcp.settings.transport_security.enable_dns_rebinding_protection = False



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
def publish_instagram_reel(caption: str, video_url: str, share_to_feed: bool = True) -> str:
    """
    Publish a Reel to Instagram from a public video URL.
    caption: The full Reel caption including hashtags.
    video_url: Publicly accessible MP4 URL. Instagram Graph API must be able to fetch it.
    share_to_feed: Whether to also share the Reel to the Instagram feed.
    """
    if not is_safe_url(video_url):
        return json.dumps({"error": "video_url not allowed for security reasons (private/internal range blocked)"})

    create_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media"
    resp = requests.post(
        create_url,
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        return json.dumps({"error": resp.json()})
    container_id = resp.json().get("id")

    # Poll the container status. Reels/video processing is asynchronous.
    status_url = f"https://graph.facebook.com/v19.0/{container_id}"
    last_status = None
    for _ in range(30):
        status_resp = requests.get(
            status_url,
            params={"fields": "status_code,status", "access_token": IG_ACCESS_TOKEN},
            timeout=15,
        )
        if status_resp.ok:
            last_status = status_resp.json()
            if last_status.get("status_code") == "FINISHED":
                break
            if last_status.get("status_code") == "ERROR":
                return json.dumps({"error": "container_processing_failed", "status": last_status})
        import time
        time.sleep(10)
    else:
        return json.dumps({"error": "container_processing_timeout", "container_id": container_id, "status": last_status})

    pub_resp = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    if not pub_resp.ok:
        return json.dumps({"error": pub_resp.json(), "container_id": container_id, "status": last_status})
    return json.dumps({
        "success": True,
        "post_id": pub_resp.json().get("id"),
        "container_id": container_id,
        "video_url": video_url,
        "status": last_status,
    })


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




@mcp.tool()
def create_branded_post(headline: str, subtitle: str, caption: str) -> str:
    """
    Creates a branded 1:1 Instagram image following Tangible Data design system and publishes it.
    headline: The main big text.
    subtitle: A smaller supporting text.
    caption: The actual Instagram caption.
    """
    # 1. Create Image (1:1 Square)
    width, height = 1080, 1080
    background_color = (26, 26, 26)  # Obsidian (#1A1A1A)
    accent_color = (146, 180, 193)     # Steel (#92B4C1)
    text_color = (245, 244, 241)     # Chalk (#F5F4F1)
    secondary_text = (154, 150, 144)  # Slate (#9A9690)
    
    img = Image.new("RGB", (width, height), color=background_color)
    draw = ImageDraw.Draw(img)
    
    # 2. Add Brand Elements (Geometric modern shapes)
    # Background accent bar at the bottom
    draw.rectangle([0, height-15, width, height], fill=accent_color)
    
    # Vertical accent line on the left
    draw.rectangle([0, 0, 10, height], fill=accent_color)
    
    # Logo shape (A minimalist data point)
    draw.ellipse([80, 80, 150, 150], outline=accent_color, width=5)
    draw.ellipse([105, 105, 125, 125], fill=accent_color)
    
    # 3. Add Text
    try:
        # On Cloud Run (Linux), we try to find common bold fonts
        # If not found, load_default will be used
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ]
        font_path = next((p for p in font_paths if os.path.exists(p)), None)
        
        if font_path:
            font_title = ImageFont.truetype(font_path, 110)
            font_sub = ImageFont.truetype(font_path, 55)
            font_footer = ImageFont.truetype(font_path, 35)
        else:
            font_title = ImageFont.load_default(size=110)
            font_sub = ImageFont.load_default(size=55)
            font_footer = ImageFont.load_default(size=35)
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    # Draw Headline (Upper case, Left aligned)
    margin = 100
    # Split headline if too long (simple logic)
    words = headline.upper().split()
    if len(words) > 3:
        line1 = " ".join(words[:len(words)//2])
        line2 = " ".join(words[len(words)//2:])
        draw.text((margin, height//2 - 180), line1, fill=text_color, font=font_title)
        draw.text((margin, height//2 - 60), line2, fill=text_color, font=font_title)
    else:
        draw.text((margin, height//2 - 120), headline.upper(), fill=text_color, font=font_title)
    
    # Draw Subtitle (Indented slightly)
    draw.text((margin, height//2 + 100), subtitle, fill=accent_color, font=font_sub)
    
    # Draw Footer
    draw.text((margin, height - 120), "TANGIBLE DATA", fill=text_color, font=font_footer)
    draw.text((margin + 300, height - 120), "|  TANGIBLEDATA.XYZ", fill=secondary_text, font=font_footer)

    # 4. Upload to GCS
    bucket_name = "instagram-mcp-assets-115449310562"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    filename = f"mcp-posts/{uuid.uuid4()}.png"
    blob = bucket.blob(filename)
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    blob.upload_from_string(img_byte_arr.getvalue(), content_type="image/png")
    # blob.make_public() # Already handled by bucket policy
    
    public_url = blob.public_url

    # 5. Publish to Instagram
    return publish_instagram_post_with_image(caption, public_url)


def publish_instagram_post_with_image(caption: str, image_url: str) -> str:
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
    return json.dumps({"success": True, "post_id": pub_resp.json().get("id"), "image_url": image_url})

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    # mcp.run(transport="streamable-http") 
    # Use uvicorn directly to ensure it listens on the correct port and host for Cloud Run
    app = mcp.streamable_http_app()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    app.add_middleware(ForceHostMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    setup_oauth(app)
    app.add_middleware(StaticApiKeyMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")

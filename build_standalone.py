#!/usr/bin/env python3
"""
Builds a self-contained version of the WellnessLabs landing page.
Downloads all external CSS, images, and fonts, then inlines/localizes them.
"""

import os
import re
import hashlib
import urllib.request
import urllib.error
import ssl
from pathlib import Path

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
CSS_DIR = ASSETS_DIR / "css"
IMG_DIR = ASSETS_DIR / "img"
FONT_DIR = ASSETS_DIR / "fonts"
INPUT_FILE = BASE_DIR / "Wellness Labs.html"
OUTPUT_FILE = BASE_DIR / "index.html"

# Create dirs
for d in [CSS_DIR, IMG_DIR, FONT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# SSL context that doesn't verify (for CDN assets)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

downloaded_cache = {}

def download_file(url, dest_dir, prefix=""):
    """Download a URL to dest_dir, return local relative path."""
    if url in downloaded_cache:
        return downloaded_cache[url]

    try:
        # Clean URL
        clean_url = url.strip()
        if clean_url.startswith("//"):
            clean_url = "https:" + clean_url
        elif clean_url.startswith("/"):
            clean_url = "https://www.trywellnesslabs.com" + clean_url

        if not clean_url.startswith("http"):
            return None

        # Generate filename from URL hash + extension
        ext = ""
        url_path = clean_url.split("?")[0]
        if "." in url_path.split("/")[-1]:
            ext = "." + url_path.split("/")[-1].split(".")[-1]
            # Limit extension length
            if len(ext) > 6:
                ext = ""

        url_hash = hashlib.md5(clean_url.encode()).hexdigest()[:12]
        filename = f"{prefix}{url_hash}{ext}"
        dest_path = dest_dir / filename

        if dest_path.exists():
            rel = os.path.relpath(dest_path, BASE_DIR)
            downloaded_cache[url] = rel
            return rel

        req = urllib.request.Request(clean_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            data = response.read()
            dest_path.write_bytes(data)
            rel = os.path.relpath(dest_path, BASE_DIR)
            downloaded_cache[url] = rel
            print(f"  ✓ Downloaded: {clean_url[:80]}... -> {rel}")
            return rel
    except Exception as e:
        print(f"  ✗ Failed: {url[:80]}... ({e})")
        return None

def process_css_urls(css_content, css_url_base):
    """Process url() references within CSS content."""
    def replace_css_url(match):
        url = match.group(1).strip("'\"")
        if url.startswith("data:"):
            return match.group(0)

        # Resolve relative URLs
        if url.startswith("//"):
            full_url = "https:" + url
        elif url.startswith("/"):
            full_url = "https://www.trywellnesslabs.com" + url
        elif url.startswith("http"):
            full_url = url
        elif css_url_base:
            full_url = css_url_base.rsplit("/", 1)[0] + "/" + url
        else:
            return match.group(0)

        # Determine if font or image
        lower = full_url.lower()
        if any(ext in lower for ext in ['.woff', '.woff2', '.ttf', '.eot', '.otf']):
            local = download_file(full_url, FONT_DIR, "font_")
        else:
            local = download_file(full_url, IMG_DIR, "css_")

        if local:
            # CSS files are in assets/css/, so relative path needs adjustment
            rel_from_css = local.replace("assets/", "")
            return "url('../" + rel_from_css + "')" if "assets/" in local else "url('" + local + "')"
        return match.group(0)

    return re.sub(r'url\(([^)]+)\)', replace_css_url, css_content)

def download_and_inline_css(html):
    """Download external CSS files and inline them."""
    print("\n📦 Processing CSS stylesheets...")

    def replace_link(match):
        tag = match.group(0)
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag)
        if not href_match:
            return tag

        href = href_match.group(1)

        # Skip non-CSS
        if 'rel="stylesheet"' not in tag and 'type="text/css"' not in tag and '.css' not in href:
            return tag

        # Resolve URL
        url = href.strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://www.trywellnesslabs.com" + url
        elif not url.startswith("http"):
            return tag

        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
                css_content = response.read().decode('utf-8', errors='replace')

            # Process url() references in CSS
            css_content = process_css_urls(css_content, url)

            print(f"  ✓ Inlined CSS: {url[:80]}...")
            return f"<style>/* Inlined from: {url[:60]} */\n{css_content}</style>"
        except Exception as e:
            print(f"  ✗ Failed CSS: {url[:80]}... ({e})")
            return tag

    # Match <link> tags for stylesheets
    html = re.sub(r'<link[^>]*(?:rel=["\']stylesheet["\']|\.css)[^>]*/?>', replace_link, html, flags=re.IGNORECASE)

    return html

def download_images(html):
    """Download images and update src/srcset references."""
    print("\n🖼️  Processing images...")

    def replace_img_src(match):
        attr = match.group(1)  # src or srcset etc
        url = match.group(2)

        if url.startswith("data:") or not url.strip():
            return match.group(0)

        local = download_file(url, IMG_DIR, "img_")
        if local:
            return f'{attr}="{local}"'
        return match.group(0)

    # Match src="..." and data-src="..."
    html = re.sub(r'((?:data-)?src)=["\']([^"\']+)["\']', replace_img_src, html)

    # Match background-image: url(...) in inline styles
    def replace_bg_url(match):
        url = match.group(1).strip("'\"")
        if url.startswith("data:"):
            return match.group(0)
        local = download_file(url, IMG_DIR, "bg_")
        if local:
            return f"background-image: url('{local}')"
        return match.group(0)

    html = re.sub(r'background-image:\s*url\(([^)]+)\)', replace_bg_url, html)

    # Match background: ... url(...) in inline styles
    def replace_bg_shorthand(match):
        prefix = match.group(1)
        url = match.group(2).strip("'\"")
        suffix = match.group(3)
        if url.startswith("data:"):
            return match.group(0)
        local = download_file(url, IMG_DIR, "bg_")
        if local:
            return f"background:{prefix}url('{local}'){suffix}"
        return match.group(0)

    html = re.sub(r'background:([^;]*?)url\(([^)]+)\)([^;]*)', replace_bg_shorthand, html)

    return html

def download_favicon(html):
    """Download favicons."""
    print("\n🔖 Processing favicons...")

    def replace_favicon(match):
        tag = match.group(0)
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag)
        if not href_match:
            return tag
        url = href_match.group(1)
        local = download_file(url, IMG_DIR, "fav_")
        if local:
            return tag.replace(href_match.group(0), f'href="{local}"')
        return tag

    html = re.sub(r'<link[^>]*rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]*>', replace_favicon, html, flags=re.IGNORECASE)
    return html

def clean_tracking_scripts(html):
    """Remove tracking/analytics scripts that won't work standalone."""
    print("\n🧹 Cleaning tracking scripts...")

    # Remove specific tracking script domains
    tracking_domains = [
        'googletagmanager.com', 'google-analytics.com', 'googleads.g.doubleclick.net',
        'facebook.net', 'fbevents.js', 'clarity.ms', 'klaviyo.com',
        'trekkie.storefront', 'trackcollect.com', 'wetracked.io',
        'optimonk.com', 'pixel.', 'beacon.js', 'config-security.com',
        'shop.app/checkouts', 'shopify.com/proxy', 'web-pixels',
        'consent-tracking', 'perf-kit', 'shop_events_listener',
        'adnabu-shopify', 'ryviu.com', 'alia-prod.com', 'aimerce',
        'aftersell', 'intelligems.io', 'triplewhale',
        'chrome-extension://'
    ]

    for domain in tracking_domains:
        # Remove script tags containing tracking domains
        html = re.sub(
            rf'<script[^>]*(?:src=["\'][^"\']*{re.escape(domain)}[^"\']*["\'])[^>]*>.*?</script>',
            '', html, flags=re.IGNORECASE | re.DOTALL
        )
        html = re.sub(
            rf'<script[^>]*(?:src=["\'][^"\']*{re.escape(domain)}[^"\']*["\'])[^>]*/?>',
            '', html, flags=re.IGNORECASE
        )

    # Remove prefetch/preconnect for checkout/tracking
    html = re.sub(r'<link[^>]*(?:prefetch|preconnect|dns-prefetch)[^>]*(?:shopify\.com/cdn/shopifycloud/checkout|monorail|shop\.app|config-security)[^>]*/?>', '', html, flags=re.IGNORECASE)

    # Remove inline tracking scripts (gtag, fbq, clarity, etc)
    html = re.sub(r'<script[^>]*>\s*(?:window\.dataLayer|function gtag|gtag\(|fbq\(|clarity\(|window\.ShopifyAnalytics).*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)

    return html

def fix_relative_urls(html):
    """Fix remaining relative URLs to point to the original domain."""
    print("\n🔗 Fixing relative URLs...")

    # Fix href="/..." links to point to original site
    html = re.sub(
        r'href="(/(?!Users)[^"]*)"',
        r'href="https://www.trywellnesslabs.com\1"',
        html
    )

    return html

def main():
    print("=" * 60)
    print("🏗️  Building self-contained WellnessLabs landing page")
    print("=" * 60)

    # Read source
    # Try the original saved file first, fall back to downloaded
    if INPUT_FILE.exists():
        html = INPUT_FILE.read_text(encoding='utf-8', errors='replace')
        print(f"\n📄 Read source: {INPUT_FILE} ({len(html):,} chars)")
    else:
        print(f"❌ Source file not found: {INPUT_FILE}")
        return

    # Process in order
    html = clean_tracking_scripts(html)
    html = download_and_inline_css(html)
    html = download_images(html)
    html = download_favicon(html)
    html = fix_relative_urls(html)

    # Remove the browser extension script
    html = re.sub(r'<script[^>]*bis_use[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*data-dynamic-id[^>]*>.*?</script>', '', html, flags=re.DOTALL)

    # Write output
    OUTPUT_FILE.write_text(html, encoding='utf-8')

    total_assets = len(list(ASSETS_DIR.rglob("*"))) if ASSETS_DIR.exists() else 0
    print(f"\n{'=' * 60}")
    print(f"✅ Done! Output: {OUTPUT_FILE}")
    print(f"   Total assets downloaded: {total_assets}")
    print(f"   Output size: {OUTPUT_FILE.stat().st_size:,} bytes")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()

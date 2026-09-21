import os
import re
import time
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ يرجى التأكد من ضبط SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://mycimamovie.online"
MOVIES_CATEGORY_URL = f"{BASE_DOMAIN}/movies.php"

def clean_title(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def get_best_poster(page):
    try:
        poster_selectors = [
            '.poster img', '.movieBanner img', '.thumbnail img',
            '.post-image img', '.img-fluid', 'article img'
        ]
        for sel in poster_selectors:
            el = page.locator(sel).first
            if el.count() > 0:
                for attr in ['src', 'data-src', 'data-original', 'srcset']:
                    val = el.get_attribute(attr)
                    if val and 'http' in val and not any(bad in val for bad in ['logo', 'avatar', 'icon']):
                        return val.split()[0]

        bg_element = page.locator('[style*="background-image"]').first
        if bg_element.count() > 0:
            style = bg_element.get_attribute('style') or ''
            bg_match = re.search(r'url\((.*?)\)', style)
            if bg_match:
                clean_url = bg_match.group(1).replace("'", "").replace('"', "")
                if 'http' in clean_url:
                    return clean_url

        meta_img = page.locator('meta[property="og:image"]').get_attribute("content")
        if meta_img and 'http' in meta_img and not any(bad in meta_img for bad in ['logo', 'icon', 'default']):
            return meta_img
    except Exception:
        pass
    return ""

def crawl_movies():
    with sync_playwright() as p:
        # إعداد المتصفح مع User-Agent لتجنب الحظر على سيرفرات GitHub Actions
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        page_num = 1
        print("\n🚀 === بدء سحب الأفلام والتحقق من Supabase ===", flush=True)

        while True:
            print(f"\n🔄 جاري فحص صفحة الأفلام رقم: {page_num}", flush=True)
            url = f"{MOVIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else MOVIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                page_num += 1
                continue
            
            # البحث عن روابط الأفلام (يمكنك تعديل المحدد بناءً على تصميم الموقع الجديد إن لم يجد روابط)
            links = page.eval_on_selector_all('a[href*="view.php"], a[href*="movie"]', "elements => elements.map(e => e.href)")
            if not links:
                print(f"🏁 وصلت إلى نهاية الصفحات عند الصفحة {page_num}", flush=True)
                break

            for link in list(set(links)):
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=25000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    movie_title = clean_title(raw_title)
                    if not movie_title:
                        continue

                    # 1. التحقق من وجود الفيلم مسبقاً في قاعدة البيانات
                    existing = supabase.table("movies").select("id").eq("title", movie_title).execute()
                    if existing.data and len(existing.data) > 0:
                        print(f"🔍 الفيلم موجود مسبقاً: {movie_title}", flush=True)
                        continue

                    year = extract_year(raw_title)
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story, .desc, .description').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()

                    poster_url = get_best_poster(page)

                    # 2. استخراج سيرفرات المشاهدة الخاصة بالفيلم
                    watch_servers = {}
                    streaming_links_list = []
                    primary_watch_url = ""

                    try:
                        page.wait_for_selector('.WatchServersList li, .servers-list li, ul.servers-list button', timeout=3000)
                    except Exception:
                        pass

                    server_elements = page.locator('.WatchServersList li, .servers-list li, ul.servers-list button, ul.servers-list a, .WatchServers li').all()
                    if not server_elements:
                        server_elements = page.locator('div[class*="server"] button, div[class*="server"] a, li[data-url]').all()

                    for btn in server_elements:
                        try:
                            s_name = btn.text_content().strip()
                            clean_sname = re.sub(r'\s+', ' ', s_name).strip()
                            
                            unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "مشاهدة الآن", "تحميل"]
                            if not clean_sname or len(clean_sname) > 25 or any(w in clean_sname for w in unwanted_texts):
                                continue

                            btn.dispatch_event('click')
                            time.sleep(0.5)

                            iframe = page.locator("iframe").first
                            if iframe.count() > 0:
                                iframe_src = iframe.get_attribute("src") or iframe.get_attribute("data-src")
                                if iframe_src and "http" in iframe_src:
                                    if not any(bad in iframe_src.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com"]):
                                        watch_servers[clean_sname] = iframe_src
                                        if iframe_src not in streaming_links_list:
                                            streaming_links_list.append(iframe_src)
                                        if not primary_watch_url:
                                            primary_watch_url = iframe_src
                        except Exception:
                            continue

                    # فحص احتياطي للـ iframe إذا لم يتم العثور على أزرار تفاعلية
                    if not watch_servers:
                        iframe = page.locator("iframe").first
                        if iframe.count() > 0:
                            src = iframe.get_attribute("src") or iframe.get_attribute("data-src") or ""
                            if src and "http" in src:
                                watch_servers["الرئيسي"] = src
                                streaming_links_list.append(src)
                                primary_watch_url = src

                    direct_links_payload = {
                        "primary_watch": primary_watch_url,
                        "watch_servers": watch_servers,
                        "streaming_links": streaming_links_list
                    }

                    movie_payload = {
                        "title": movie_title,
                        "poster_url": poster_url,
                        "year": year,
                        "description": description,
                        "watch_url": link,
                        "direct_links": direct_links_payload,
                        "category_type": "احدث الافلام"
                    }
                    
                    res_insert = supabase.table("movies").upsert(movie_payload, on_conflict="title").execute()
                    if res_insert.data:
                        print(f"🎬 تمت إضافة الفيلم بنجاح: {movie_title} (سيرفرات: {len(watch_servers)})", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_movies()

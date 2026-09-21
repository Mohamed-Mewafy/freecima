import os
import re
import time
from urllib.parse import urljoin
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
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا|ماي سيما|مايسيما|موقع|mycima)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def get_best_poster(page, base_url="https://mycimamovie.online"):
    try:
        # 1. فحص وسم og:image
        meta_img = page.locator('meta[property="og:image"]').get_attribute("content")
        if meta_img and not any(bad in meta_img.lower() for bad in ['logo', 'icon', 'default', 'banner']):
            return urljoin(base_url, meta_img.strip())

        # 2. فحص عناصر الصور مع دعم التحميل الكسول والمسارات النسبية
        poster_selectors = [
            '.Poster img', '.poster img', '.image img', '.single-poster img',
            '.movie-image img', '.post-thumbnail img', '.thumb img',
            '.entry-thumbnail img', 'article img', '.img-fluid'
        ]
        
        for sel in poster_selectors:
            el = page.locator(sel).first
            if el.count() > 0:
                for attr in ['data-src', 'data-lazy-src', 'data-original', 'src', 'srcset']:
                    val = el.get_attribute(attr)
                    if val:
                        clean_val = val.split()[0].strip()
                        if clean_val and not any(bad in clean_val.lower() for bad in ['logo', 'avatar', 'icon', 'svg']):
                            return urljoin(base_url, clean_val)

        # 3. فحص الخلفيات background-image
        bg_elements = page.locator('[style*="background-image"], .poster[style]').all()
        for bg_el in bg_elements:
            style = bg_el.get_attribute('style') or ''
            bg_match = re.search(r'url\([\'"]?(.*?)[\'"]?\)', style)
            if bg_match:
                clean_url = bg_match.group(1).strip()
                if clean_url and not any(bad in clean_url.lower() for bad in ['logo', 'icon', 'default']):
                    return urljoin(base_url, clean_url)

    except Exception:
        pass
    return ""

def crawl_movies():
    with sync_playwright() as p:
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
        print("\n🚀 === بدء سحب الأفلام مع البوسترات وتفادي تعارض الروابط ===", flush=True)

        while True:
            print(f"\n🔄 جاري فحص صفحة الأفلام رقم: {page_num}", flush=True)
            url = f"{MOVIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else MOVIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                page_num += 1
                continue
            
            # جلب الروابط وتصفية القوائم والأقسام
            all_page_links = page.eval_on_selector_all('a[href]', "elements => elements.map(e => e.href)")
            movie_links = []
            for l in set(all_page_links):
                if any(k in l for k in ['view.php', 'view-movie.php', 'watch.php', 'film/']) and not any(b in l for b in ['genre=', 'category=', 'account', 'login', 'register', 'contact']):
                    movie_links.append(l)

            if not movie_links:
                print(f"🏁 وصلت إلى نهاية الصفحات عند الصفحة {page_num}", flush=True)
                break

            for link in movie_links:
                try:
                    # 1. التحقق المسبق باستخدام watch_url لتجنب التكرار وتفادي خطأ القيد الفريد
                    existing = supabase.table("movies_cima").select("id").eq("watch_url", link).execute()
                    if existing.data and len(existing.data) > 0:
                        print(f"🔍 الرابط مسجل مسبقاً، تم التخطي: {link}", flush=True)
                        continue

                    page.goto(link, wait_until="domcontentloaded", timeout=25000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else ""
                    movie_title = clean_title(raw_title)
                    
                    # استبعاد أسماء الأقسام والقوائم غير المرغوبة
                    unwanted_words = ["أكشن", "دراما", "رعب", "كوميدي", "رومانسي", "اثارة", "إثارة", "برامج", "انمي", "أنمي", "الفلوس", "واقعي", "حساب", "دخول", "افلام", "أحدث"]
                    if not movie_title or len(movie_title) < 2 or movie_title in unwanted_words:
                        continue

                    year = extract_year(raw_title)
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story, .desc, .description, .story-movie').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()

                    poster_url = get_best_poster(page, link)

                    # 2. فحص صفحة المشاهدة والسيرفرات
                    watch_button_links = page.eval_on_selector_all('a[href*="watch.php"], a[href*="play.php"]', "elements => elements.map(e => e.href)")
                    
                    watch_page = browser.new_page()
                    watch_page.set_default_timeout(25000)
                    
                    if watch_button_links:
                        target_watch = watch_button_links[0].replace("watch.php", "play.php")
                        watch_page.goto(target_watch, wait_until="domcontentloaded", timeout=25000)
                    else:
                        watch_page.goto(link, wait_until="domcontentloaded", timeout=25000)

                    try:
                        watch_page.wait_for_selector('.WatchServersList li, .servers-list li, ul.servers-list button', timeout=4000)
                    except Exception:
                        pass

                    watch_servers = {}
                    streaming_links_list = []
                    primary_watch_url = ""

                    server_elements = watch_page.locator('.WatchServersList li, .servers-list li, ul.servers-list button, ul.servers-list a, .WatchServers li').all()
                    if not server_elements:
                        server_elements = watch_page.locator('div[class*="server"] button, div[class*="server"] a, li[data-url], li[data-embed]').all()

                    for btn in server_elements:
                        try:
                            s_name = btn.text_content().strip()
                            clean_sname = re.sub(r'\s+', ' ', s_name).strip()
                            
                            unwanted_btn_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "تحميل"]
                            if not clean_sname or len(clean_sname) > 25 or any(w in clean_sname for w in unwanted_btn_texts):
                                continue

                            btn.dispatch_event('click')
                            time.sleep(0.5)

                            iframe = watch_page.locator("iframe").first
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

                    if not watch_servers:
                        time.sleep(1.0)
                        iframe = watch_page.locator("iframe").first
                        if iframe.count() > 0:
                            src = iframe.get_attribute("src") or iframe.get_attribute("data-src") or ""
                            if src and "http" in src:
                                watch_servers["الرئيسي"] = src
                                streaming_links_list.append(src)
                                primary_watch_url = src

                    watch_page.close()

                    # تخطي الصفحات التي لا تحتوي على أي سيرفرات تشغيل
                    if not watch_servers:
                        continue

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
                    
                    # 3. الحفظ في Supabase بناءً على قيد watch_url
                    res_insert = supabase.table("movies_cima").upsert(movie_payload, on_conflict="watch_url").execute()
                    if res_insert.data:
                        print(f"🎬 تمت إضافة: {movie_title} | البوستر: {'✔️' if poster_url else '❌'} | سيرفرات: ({len(watch_servers)})", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_movies()

import os
import re
import time
import json
import urllib.request
import urllib.parse
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "b6b668045bb658eb025ed996abcb0f56")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ يرجى التأكد من ضبط SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://mycimamovie.online"
MOVIES_CATEGORY_URL = f"{BASE_DOMAIN}/movies.php"
CATEGORY_TAG = "احدث الافلام"

JUNK_TITLES = {
    "افلام كوميدي", "ات هندي", "أحدث الات", "ات تركي", "ات عربية", "أحدث الحلقات",
    "ات رمضان", "رمضان", "واقعي", "القصص", "انمي", "أنمي", "الفلوس", "برامج",
    "اثارة", "إثارة", "مغامرة", "اكشن", "أكشن", "رومانسي", "غموض", "دراما",
    "رعب", "حساب", "تسجيل", "دخول", "الرئيسية", "افلام", "أحدث الافلام", "أحدث الأفلام"
}

def is_junk_title(title):
    t = title.strip().lower()
    if t in JUNK_TITLES or len(t) < 3:
        return True
    if t.startswith("ات ") or t.startswith("افلام "):
        return True
    return False

def clean_title_strict(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا|ماي\s*سيما|مايسيما|وي\s*سيما|ويسيما|mycima|cima)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def clean_movie_story(raw_story):
    if not raw_story or len(raw_story.strip()) < 5:
        return "لا يوجد وصف متوفر حالياً."

    story = raw_story.strip()
    match = re.search(r'(?:قصة\s*(?:الفيلم|المسلسل|العمل)?\s*[:\-]\s*)(.+)', story, re.DOTALL | re.IGNORECASE)
    if match:
        story = match.group(1).strip()

    stop_markers = [
        r'يوتيوب مشاهدة', r'مشاهدة بجودة', r'شاهد مباشر', r'تحميل فيلم',
        r'الكلمات المفتاحية', r'علي موقع ماي سيما', r'ماي سيما', r'اون لاين'
    ]
    for marker in stop_markers:
        parts = re.split(marker, story, flags=re.IGNORECASE)
        if len(parts) > 1 and len(parts[0].strip()) > 15:
            story = parts[0].strip()

    remove_patterns = [
        r'مشاهدة\s+مباشرة\s+وتحميل\s+.*?(?=بطولة|يروي|تدور|تبدأ|في|$)',
        r'بطولة\s*:\s*.*?(?=يروي|تدور|تبدأ|في|$)',
        r'Full HD|1080p|720p|HD|SD|4K',
        r'أكثر من سيرفر', r'حصري\s+علي', r'موقع\s+ماي\s*سيما', r'افلام\s+عربي'
    ]
    for p in remove_patterns:
        story = re.sub(p, '', story, flags=re.IGNORECASE)

    story = " ".join(story.split()).strip(" :-،,.")
    return story if len(story) > 10 else raw_story.strip()

def fetch_tmdb_poster_accurate(title, year=None):
    try:
        query = urllib.parse.quote(title)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&language=ar"
        if year:
            url += f"&primary_release_year={year}"

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as res:
            data = json.loads(res.read().decode('utf-8'))
            results = data.get("results", [])
            if results and results[0].get("poster_path"):
                return f"https://image.tmdb.org/t/p/w500{results[0]['poster_path']}"
    except Exception:
        pass
    return ""

def fix_only_scraped_movies():
    print(f"\n🛠️ === فحص وتصحيح أفلام السكربت فقط وتفادي التكرار ===\n", flush=True)

    res = supabase.table("movies_cima") \
        .select("id, title, description, poster_url, year, watch_url") \
        .like("watch_url", f"%{BASE_DOMAIN}%") \
        .execute()

    movies = res.data or []
    print(f"📊 تم العثور على {len(movies)} فيلم مسحوب للمراجعة...", flush=True)

    seen_titles = set()

    for m in movies:
        m_id = m["id"]
        raw_title = m.get("title", "")
        old_desc = m.get("description", "")
        current_poster = m.get("poster_url") or ""
        year = m.get("year")

        if is_junk_title(raw_title):
            try:
                supabase.table("movies_cima").delete().eq("id", m_id).execute()
                print(f"🗑️ حذف قسم وهمي: {raw_title}", flush=True)
            except Exception:
                pass
            continue

        clean_name = clean_title_strict(raw_title)
        if not clean_name or is_junk_title(clean_name):
            try:
                supabase.table("movies_cima").delete().eq("id", m_id).execute()
            except Exception:
                pass
            continue

        # حذف التكرارات مباشرة
        if clean_name in seen_titles:
            try:
                supabase.table("movies_cima").delete().eq("id", m_id).execute()
                print(f"🗑️ حذف نسخة مكررة: {clean_name}", flush=True)
            except Exception:
                pass
            continue

        seen_titles.add(clean_name)

        clean_desc = clean_movie_story(old_desc)
        new_poster = current_poster

        if not current_poster or any(bad in current_poster.lower() for bad in ['logo', 'icon', 'default', 'social-thumb']):
            poster_tmdb = fetch_tmdb_poster_accurate(clean_name, year)
            if poster_tmdb:
                new_poster = poster_tmdb

        update_payload = {}
        if clean_name != raw_title:
            update_payload["title"] = clean_name
        if clean_desc and clean_desc != old_desc:
            update_payload["description"] = clean_desc
        if new_poster and new_poster != current_poster:
            update_payload["poster_url"] = new_poster

        if update_payload:
            try:
                supabase.table("movies_cima").update(update_payload).eq("id", m_id).execute()
                print(f"✅ تم تحديث بيانات: {clean_name}", flush=True)
            except Exception as e:
                # إذا حدث تعارض عنوان أثناء التحديث نحذف هذا السجل الزائد
                if "23505" in str(e) or "unique constraint" in str(e):
                    supabase.table("movies_cima").delete().eq("id", m_id).execute()
                    print(f"🗑️ إزالة تعارض قديم للفيلم: {clean_name}", flush=True)
                else:
                    print(f"⚠️ خطأ أثناء التحديث: {e}", flush=True)

def crawl_and_scrape():
    print("\n🚀 === بدء استكمال سحب الأفلام الجديدة وسيرفراتها ===", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        page_num = 1

        while True:
            print(f"\n🔄 جاري فحص صفحة الأفلام رقم: {page_num}", flush=True)
            url = f"{MOVIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else MOVIES_CATEGORY_URL

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                page_num += 1
                continue

            items = page.evaluate("""() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="view.php"], a[href*="view-movie.php"], a[href*="watch.php"]');
                links.forEach(a => {
                    const href = a.href;
                    if (href.includes('genre=') || href.includes('category=') || href.includes('account')) return;
                    
                    let img = a.querySelector('img');
                    if (!img && a.parentElement) img = a.parentElement.querySelector('img');
                    
                    let imgSrc = '';
                    if (img) {
                        imgSrc = img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('data-original') || img.src || '';
                    }
                    results.push({ href: href, poster: imgSrc });
                });
                return results;
            }""")

            if not items:
                print(f"🏁 انتهت قائمة الصفحات عند الصفحة {page_num}", flush=True)
                break

            unique_items = {item['href']: item['poster'] for item in items}

            for link, card_poster in unique_items.items():
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=25000)

                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else ""
                    movie_title = clean_title_strict(raw_title)
                    year = extract_year(raw_title)

                    if not movie_title or is_junk_title(movie_title):
                        continue

                    # فحص وجود الفيلم مسبقاً بالاسم أو بالرابط لمنع تعارض movies_cima_title_key
                    existing_check = supabase.table("movies_cima").select("id, poster_url, description").or_(f"title.eq.{movie_title},watch_url.eq.{link}").execute()
                    
                    final_poster = urljoin(BASE_DOMAIN, card_poster) if card_poster and 'http' not in card_poster else card_poster
                    meta_locator = page.locator('meta[property="og:image"]')
                    if meta_locator.count() > 0:
                        meta_img = meta_locator.first.get_attribute("content")
                        if meta_img and not any(bad in meta_img.lower() for bad in ['logo', 'icon', 'default']):
                            final_poster = urljoin(BASE_DOMAIN, meta_img.strip())

                    if not final_poster:
                        final_poster = fetch_tmdb_poster_accurate(movie_title, year)

                    raw_description = "لا يوجد وصف"
                    desc_el = page.locator('.story, .desc, .description, .story-movie').first
                    if desc_el.count() > 0:
                        raw_description = desc_el.text_content().strip()
                    clean_description = clean_movie_story(raw_description)

                    # إذا كان الفيلم مسجلاً مسبقاً، نكتفي بتحديثه عبر المعرف id ولا ننشئ سطراً جديداً
                    if existing_check.data and len(existing_check.data) > 0:
                        target_id = existing_check.data[0]["id"]
                        supabase.table("movies_cima").update({
                            "poster_url": final_poster,
                            "year": year,
                            "description": clean_description
                        }).eq("id", target_id).execute()
                        continue

                    # سحب السيرفرات من صفحة المشاهدة
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

                    if not watch_servers:
                        continue

                    direct_links_payload = {
                        "primary_watch": primary_watch_url,
                        "watch_servers": watch_servers,
                        "streaming_links": streaming_links_list
                    }

                    movie_payload = {
                        "title": movie_title,
                        "poster_url": final_poster,
                        "year": year,
                        "description": clean_description,
                        "watch_url": link,
                        "direct_links": direct_links_payload,
                        "category_type": CATEGORY_TAG
                    }

                    # استخدام on_conflict="title" للتوافق مع القيد الفريد
                    supabase.table("movies_cima").upsert(movie_payload, on_conflict="title").execute()
                    print(f"🎬 أُضيف فيلم جديد: {movie_title} ({year}) | القصة: نظيفة | سيرفرات: ({len(watch_servers)})", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ أثناء معالجة فيلم: {e}", flush=True)

            page_num += 1

        browser.close()

if __name__ == "__main__":
    fix_only_scraped_movies()
    crawl_and_scrape()

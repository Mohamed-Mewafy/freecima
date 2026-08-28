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

BASE_DOMAIN = "https://cima.land"
SERIES_CATEGORY_URL = f"{BASE_DOMAIN}/moslslat.php"

def clean_title(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def extract_episode_number(title):
    match = re.search(r'(?:الحلقة|ep|حلقة)\s*(\d+)', title, re.IGNORECASE)
    if match:
        return int(match.group(1))
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', title)
    nums = re.findall(r'\d+', clean)
    return int(nums[0]) if nums else 1

def get_best_poster(page):
    try:
        poster_selectors = [
            '.poster img', '.seriesBanner img', '.thumbnail img',
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

def crawl_series():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(30000)

        page_num = 1
        print("\n🚀 === بدء السحب واقتناص السيرفرات عبر الضغط الفعلي وحصاد الـ AJAX ===", flush=True)

        while True:
            print(f"\n🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
            url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                page_num += 1
                continue
            
            links = page.eval_on_selector_all('a[href*="view-serie.php"]', "elements => elements.map(e => e.href)")
            if not links:
                print(f"🏁 وصلت إلى نهاية الصفحات عند الصفحة {page_num}", flush=True)
                break

            for link in list(set(links)):
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    series_title = clean_title(raw_title)
                    if not series_title:
                        continue

                    existing = supabase.table("tv_series").select("id").eq("title", series_title).execute()
                    if existing.data and len(existing.data) > 0:
                        print(f"⏩ المسلسل موجود مسبقاً، تم التخطي: {series_title}", flush=True)
                        continue

                    year = extract_year(raw_title)
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()

                    poster_url = get_best_poster(page)

                    series_payload = {
                        "title": series_title,
                        "poster_url": poster_url,
                        "year": year,
                        "description": description,
                        "watch_url": link,
                        "category_type": "احدث المسلسلات"
                    }
                    
                    res_insert = supabase.table("tv_series").upsert(series_payload, on_conflict="title").execute()
                    if not res_insert.data:
                        continue
                    series_id = res_insert.data[0]['id']
                    print(f"🎬 تم إدخال المسلسل: {series_title}", flush=True)

                    episode_links = page.eval_on_selector_all(
                        'a[href*="watch.php"], a[href*="play.php"], a[href*="episode"]', 
                        "elements => elements.map(e => e.href)"
                    )
                    unique_episodes = list(set(episode_links))

                    ep_page = browser.new_page()
                    ep_page.set_default_timeout(30000)

                    for ep_link in unique_episodes:
                        try:
                            play_url = ep_link.replace("watch.php", "play.php")
                            ep_page.goto(play_url, wait_until="domcontentloaded", timeout=30000)
                            
                            ep_raw_title = ep_page.locator('h1').first.text_content().strip() if ep_page.locator('h1').count() > 0 else "حلقة"
                            ep_number = extract_episode_number(ep_raw_title)
                            
                            watch_servers = {}
                            streaming_links_list = []
                            primary_watch_url = ""

                            # تحديد أزرار السيرفرات بناءً على وسوم li أو أزرار القائمة داخل حاوية السيرفرات
                            server_elements = ep_page.locator('.WatchServersList li, .servers-list li, ul.servers-list button, ul.servers-list a, div.server-btn, [data-url], [data-embed]').all()

                            if not server_elements:
                                # محدد شامل كخطة احتياطية للأزرار المشابهة
                                server_elements = ep_page.locator('ul li:has(i), ul li:has(span)').all()

                            for btn in server_elements:
                                try:
                                    s_name = btn.text_content().strip()
                                    clean_sname = re.sub(r'\s+', ' ', s_name).strip()
                                    
                                    unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "مشاهدة الآن", "تحميل", "Download"]
                                    if not clean_sname or len(clean_sname) > 25 or any(w in clean_sname for w in unwanted_texts):
                                        continue

                                    # تفعيل حدث النقر عبر JavaScript مباشرة لضمان تنفيذ السكربت الداخلي للموقع
                                    btn.dispatch_event('click')
                                    time.sleep(0.8)  # مهلة كافية لتحميل الـ AJAX وتحديث الـ Iframe

                                    # جلب رابط السيرفر من الـ Iframe بعد تحديثه
                                    iframe = ep_page.locator("iframe").first
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

                            # إذا لم يلتقط أي سيرفر بالضغط، أخذ الـ Iframe الحالي بالصفحة
                            if not watch_servers:
                                iframe = ep_page.locator("iframe").first
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

                            episode_payload = {
                                "series_id": series_id,
                                "season_number": 1,
                                "episode_number": ep_number,
                                "title": ep_raw_title,
                                "watch_url": play_url,
                                "direct_links": direct_links_payload
                            }
                            
                            supabase.table("episodes_cima").upsert(episode_payload, on_conflict="series_id, season_number, episode_number").execute()
                            print(f"      ✔️ حلقة {ep_number}: تمت إضافة ({len(watch_servers)}) سيرفرات -> [{', '.join(watch_servers.keys())}]", flush=True)

                        except Exception:
                            continue
                    
                    ep_page.close()

                except Exception as e:
                    print(f"⚠️ خطأ بالمسلسل: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_series()

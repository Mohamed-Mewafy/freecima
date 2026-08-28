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
        print("\n🚀 === بدء السحب واقتناص سيرفرات المشاهدة ===", flush=True)

        while True:
            print(f"\n🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
            url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"⚠️ فشل تحميل الصفحة {page_num}، جاري التخطي...", flush=True)
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
                    ep_page.set_default_timeout(20000)

                    for ep_link in unique_episodes:
                        try:
                            play_url = ep_link.replace("watch.php", "play.php")
                            ep_page.goto(play_url, wait_until="domcontentloaded", timeout=20000)
                            
                            ep_raw_title = ep_page.locator('h1').first.text_content().strip() if ep_page.locator('h1').count() > 0 else "حلقة"
                            ep_number = extract_episode_number(ep_raw_title)
                            
                            watch_servers = {}
                            streaming_links_list = []
                            primary_watch_url = ""

                            # 1. استخراج الروابط المباشرة المخزنة في attributes الأزرار (أسرع وأضمن طريقة في cima.land)
                            data_server_elements = ep_page.locator('[data-url], [data-watch], [data-link], .WatchServersList li, .servers-list li, .WatchServers li').all()
                            
                            for el in data_server_elements:
                                try:
                                    s_name = el.text_content().strip()
                                    clean_sname = re.sub(r'\s+', ' ', s_name).strip()
                                    
                                    # استخراج الرابط المباشر إن وجد في attributes
                                    direct_embed = el.get_attribute('data-url') or el.get_attribute('data-watch') or el.get_attribute('data-link')
                                    
                                    if direct_embed and 'http' in direct_embed:
                                        watch_servers[clean_sname] = direct_embed
                                        if direct_embed not in streaming_links_list:
                                            streaming_links_list.append(direct_embed)
                                        if not primary_watch_url:
                                            primary_watch_url = direct_embed
                                    else:
                                        # 2. النقر الفعلي في حال عدم وجود الرابط كـ attribute
                                        el.click(force=True, timeout=1000)
                                        time.sleep(0.5)
                                        
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

                            # 3. خطة احتياطية في حال عدم العثور على أزرار: أخذ الـ Iframe الرئيسي في الصفحة
                            if not primary_watch_url:
                                iframes = ep_page.locator("iframe").all()
                                for idx, iframe in enumerate(iframes):
                                    src = iframe.get_attribute("src") or iframe.get_attribute("data-src") or ""
                                    if src and "http" in src and not any(bad in src.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com"]):
                                        server_label = f"سيرفر رئيسي {idx + 1}"
                                        watch_servers[server_label] = src
                                        if src not in streaming_links_list:
                                            streaming_links_list.append(src)
                                        if not primary_watch_url:
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
                            print(f"      ✔️ حلقة {ep_number}: تمت الإضافة بـ ({len(watch_servers)}) سيرفر", flush=True)

                        except Exception as ep_err:
                            continue
                    
                    ep_page.close()

                except Exception as e:
                    print(f"⚠️ خطأ بالمسلسل: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_series()

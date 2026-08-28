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

def extract_all_servers(page):
    watch_servers = {}
    streaming_links_list = []

    try:
        page.evaluate("window.scrollBy(0, 300)")
        time.sleep(0.5)

        server_buttons = page.locator('ul.servers-list li, .watch-servers li, .embed-player-tabs button, .watch-servers button, button[data-url], li[data-link]').all()

        if not server_buttons:
            server_buttons = page.locator('li, button, a').all()

        for btn in server_buttons:
            try:
                if not btn.is_visible():
                    continue

                btn_text = btn.text_content().strip()
                unwanted = ["مشاهدة الآن", "تحميل الآن", "تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "تحميل", "Download"]
                if not btn_text or len(btn_text) > 20 or any(w in btn_text for w in unwanted):
                    continue

                server_name = re.sub(r'\s+', ' ', btn_text).strip()

                direct_data_url = btn.get_attribute("data-link") or btn.get_attribute("data-url") or btn.get_attribute("data-src")
                if direct_data_url and "http" in direct_data_url:
                    if not any(bad in direct_data_url.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com"]):
                        watch_servers[server_name] = direct_data_url
                        if direct_data_url not in streaming_links_list:
                            streaming_links_list.append(direct_data_url)
                        continue

                btn.click(force=True, timeout=2000)
                time.sleep(0.7)

                iframe_el = page.locator("iframe#player_iframe, .embed-player iframe, iframe[src*='http']").first
                if iframe_el.count() > 0:
                    iframe_src = iframe_el.get_attribute("src") or iframe_el.get_attribute("data-src")
                    if iframe_src and "http" in iframe_src:
                        if not any(bad in iframe_src.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com"]):
                            watch_servers[server_name] = iframe_src
                            if iframe_src not in streaming_links_list:
                                streaming_links_list.append(iframe_src)
            except Exception:
                continue

    except Exception as e:
        print(f"⚠️ تنبيه أثناء استخراج السيرفرات: {e}", flush=True)

    return watch_servers, streaming_links_list

def crawl_series(context):
    print("\n🚀 === بدء السحب الذكي (سحب كافة سيرفرات المشاهدة المتاحة) ===", flush=True)
    page_num = 1
    main_page = context.new_page()
    main_page.set_default_timeout(45000)

    while True:
        print(f"🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
        url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
        
        try:
            main_page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            page_num += 1
            continue
        
        links = main_page.eval_on_selector_all('a[href*="view-serie.php"]', "elements => elements.map(e => e.href)")
        if not links:
            print(f"🏁 نهاية صفحات المسلسلات عند الصفحة {page_num}", flush=True)
            break

        for link in list(set(links)):
            try:
                main_page.goto(link, wait_until="domcontentloaded", timeout=45000)
                
                raw_title = main_page.locator('h1').first.text_content().strip() if main_page.locator('h1').count() > 0 else "بدون عنوان"
                series_title = clean_title(raw_title)
                if not series_title:
                    continue

                existing = supabase.table("tv_series").select("id").eq("title", series_title).execute()
                if existing.data:
                    print(f"⏩ المسلسل موجود مسبقاً، تم التخطي: {series_title}", flush=True)
                    continue

                year = extract_year(raw_title)
                description = "لا يوجد وصف"
                desc_el = main_page.locator('.story, .desc, .description').first
                if desc_el.count() > 0:
                    description = desc_el.text_content().strip()

                poster_url = get_best_poster(main_page)

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
                print(f"🎬 تم إدخال المسلسل: {series_title} | البوستر: {'✅ تم الجلب' if poster_url else '❌ غير متاح'}", flush=True)

                episode_links = main_page.eval_on_selector_all('a[href*="watch.php?vid="], a[href*="play.php"]', "elements => elements.map(e => e.href)")
                unique_episodes = list(set(episode_links))

                ep_page = context.new_page()
                ep_page.set_default_timeout(30000)

                for ep_link in unique_episodes:
                    try:
                        play_url = ep_link.replace("watch.php", "play.php")
                        ep_page.goto(play_url, wait_until="domcontentloaded", timeout=30000)
                        
                        ep_raw_title = ep_page.locator('h1').first.text_content().strip() if ep_page.locator('h1').count() > 0 else "حلقة"
                        ep_number = extract_episode_number(ep_raw_title)
                        
                        watch_servers, streaming_links_list = extract_all_servers(ep_page)
                        primary_watch_url = streaming_links_list[0] if streaming_links_list else ""

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
                    except Exception:
                        continue
                
                ep_page.close()
                print(f"      ✔️ تم جلب ({len(watch_servers)}) سيرفر مشاهدة للحلقة.", flush=True)

            except Exception as e:
                print(f"⚠️ خطأ أثناء معالجة المسلسل: {e}", flush=True)
        
        page_num += 1
    main_page.close()

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        crawl_series(context)
        browser.close()
    print("\n✅ تم الانتهاء بنجاح!", flush=True)

if __name__ == "__main__":
    main()

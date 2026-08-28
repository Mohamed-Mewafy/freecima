import os
import re
import time
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://cima.land"
SERIES_CATEGORY_URL = f"{BASE_DOMAIN}/moslslات.php" if False else f"{BASE_DOMAIN}/moslslat.php"

def clean_title(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|\d{4}|الحلقة|\d+)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[:\-]', '', clean)
    return " ".join(clean.split())

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def extract_episode_number(title):
    match = re.search(r'(?:الحلقة|ep|حلقة)\s*(\d+)', title, re.IGNORECASE)
    if match:
        return int(match.group(1))
    nums = re.findall(r'\d+', title)
    if nums:
        return int(nums[-1])
    return 1

def get_best_poster(page):
    try:
        meta_img = page.locator('meta[property="og:image"]')
        if meta_img.count() > 0:
            content = meta_img.get_attribute("content")
            if content and "http" in content:
                return content
    except:
        pass

    try:
        img_element = page.locator('.poster img, .seriesBanner img, .thumbnail img, img').first
        if img_element.count() > 0:
            src = img_element.get_attribute("src") or img_element.get_attribute("data-src") or ""
            if src and "http" in src:
                return src
    except:
        pass
    return ""

def crawl_series(page):
    print("\n🚀 === بدء السحب (نسخة محسنة وسريعة) ===", flush=True)
    page_num = 1
    while True:
        print(f"🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
        url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except:
            page_num += 1
            continue
        
        links = page.eval_on_selector_all('a[href*="view-serie.php"]', "elements => elements.map(e => e.href)")
        
        if not links or len(links) == 0:
            print(f"🏁 نهاية صفحة المسلسلات عند الصفحة {page_num}", flush=True)
            break

        unique_links = list(set(links))
        print(f"📄 وُجد {len(unique_links)} مسلسل في الصفحة {page_num}", flush=True)

        for link in unique_links:
            try:
                page.goto(link, wait_until="domcontentloaded", timeout=45000)
                
                raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                series_title = clean_title(raw_title)
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
                
                supabase.table("tv_series").upsert(series_payload, on_conflict="title").execute()
                
                series_id_res = supabase.table("tv_series").select("id").eq("title", series_title).execute()
                if not series_id_res.data:
                    continue
                series_id = series_id_res.data[0]['id']
                
                print(f"🎬 معالجة المسلسل: {series_title}", flush=True)

                episode_links = page.eval_on_selector_all('a[href*="watch.php?vid="], a[href*="play.php"]', "elements => elements.map(e => e.href)")
                unique_episodes = list(set(episode_links))

                for ep_link in unique_episodes:
                    try:
                        play_url = ep_link.replace("watch.php", "play.php")
                        page.goto(play_url, wait_until="domcontentloaded", timeout=30000)
                        
                        ep_raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "حلقة"
                        ep_number = extract_episode_number(ep_raw_title)
                        
                        watch_servers = {}
                        primary_watch_url = ""
                        
                        try:
                            server_buttons = page.locator('button, a').all()
                            servers_info = []
                            for btn in server_buttons:
                                try:
                                    if not btn.is_visible():
                                        continue
                                    btn_text = btn.text_content().strip()
                                    unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK"]
                                    if not btn_text or len(btn_text) > 15 or any(w in btn_text for w in unwanted_texts):
                                        continue
                                    servers_info.append((btn, btn_text))
                                except:
                                    continue

                            for btn, s_name in servers_info:
                                try:
                                    btn.click(timeout=1000)
                                    time.sleep(0.4) # تقليل وقت الانتظار لتسريع العملية وعدم حدوث تعليق
                                    
                                    iframe = page.locator("iframe").first
                                    if iframe.count() > 0:
                                        iframe_src = iframe.get_attribute("src")
                                        if iframe_src and "http" in iframe_src:
                                            watch_servers[s_name] = iframe_src
                                            if not primary_watch_url:
                                                primary_watch_url = iframe_src
                                except:
                                    continue
                        except:
                            pass

                        if not primary_watch_url:
                            iframe = page.locator("iframe").first
                            if iframe.count() > 0:
                                primary_watch_url = iframe.get_attribute("src") or ""

                        direct_links_payload = {
                            "primary_watch": primary_watch_url,
                            "watch_servers": watch_servers
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
                    except:
                        continue

                print(f"      ✔️ تمت حلقة المسلسل بنجاح.", flush=True)

            except Exception as e:
                print(f"⚠️ خطأ: {e}", flush=True)
        
        page_num += 1

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(45000)

        crawl_series(page)
        browser.close()
    print("\n✅ تم الانتهاء بنجاح!", flush=True)

if __name__ == "__main__":
    main()

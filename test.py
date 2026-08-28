import os
import re
import time
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://cima.land"
SERIES_CATEGORY_URL = f"{BASE_DOMAIN}/moslslat.php"

def clean_title(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|\d{4}|الحلقة|\d+)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[:\-]', '', clean)
    return " ".join(clean.split())

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def extract_episode_number(title):
    match = re.search(r'(?:الحلقة|ep)\s*(\d+)', title, re.IGNORECASE)
    return int(match.group(1)) if match else 1

def crawl_series_pages():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(60000)

        page_num = 1
        while True:
            print(f"🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
            url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"⚠️ فشل تحميل صفحة المسلسلات {page_num}...", flush=True)
                page_num += 1
                continue
            
            links = page.eval_on_selector_all('a[href*="view-serie.php"]', "elements => elements.map(e => e.href)")
            
            if not links or len(links) == 0:
                print(f"🏁 وصلت إلى نهاية صفحات المسلسلات (الصفحة {page_num} فارغة).", flush=True)
                break

            unique_links = list(set(links))
            print(f"📄 وُجد {len(unique_links)} مسلسل في الصفحة {page_num}", flush=True)

            for link in unique_links:
                try:
                    # 1. الدخول لصفحة المسلسل الرئيسية
                    page.goto(link, wait_until="domcontentloaded", timeout=60000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    series_title = clean_title(raw_title)
                    year = extract_year(raw_title)
                    
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()

                    poster_url = ""
                    meta_img = page.locator('meta[property="og:image"]')
                    if meta_img.count() > 0:
                        poster_url = meta_img.get_attribute("content") or ""

                    # حفظ المسلسل في جدول tv_series مع تعيين category_type إلى "احدث المسلسلات"
                    series_payload = {
                        "title": series_title,
                        "poster_url": poster_url,
                        "year": year,
                        "description": description,
                        "watch_url": link,
                        "category_type": "احدث المسلسلات"
                    }
                    
                    supabase.table("tv_series").upsert(series_payload, on_conflict="title").execute()
                    
                    # جلب الـ ID الخاص بالمسلسل
                    series_id_res = supabase.table("tv_series").select("id").eq("title", series_title).execute()
                    if not series_id_res.data:
                        continue
                    series_id = series_id_res.data[0]['id']
                    
                    print(f"🎬 جاري معالجة المسلسل: {series_title} (ID: {series_id})", flush=True)

                    # 2. استخراج روابط الحلقات من صفحة المسلسل
                    episode_links = page.eval_on_selector_all('a[href*="watch.php?vid="], a[href*="play.php"]', "elements => elements.map(e => e.href)")
                    unique_episodes = list(set(episode_links))
                    print(f"   📌 تم العثور على {len(unique_episodes)} حلقة.", flush=True)

                    for ep_link in unique_episodes:
                        try:
                            play_url = ep_link.replace("watch.php", "play.php")
                            page.goto(play_url, wait_until="domcontentloaded", timeout=60000)
                            
                            ep_raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "حلقة"
                            ep_number = extract_episode_number(ep_raw_title)
                            
                            # حفظ الحلقة في جدول episodes
                            episode_payload = {
                                "series_id": series_id,
                                "episode_number": ep_number,
                                "title": ep_raw_title,
                                "watch_url": play_url
                            }
                            
                            supabase.table("episodes").upsert(episode_payload, on_conflict="series_id, episode_number").execute()
                            
                            # جلب ID الحلقة للربط مع episode_sources
                            ep_id_res = supabase.table("episodes").select("id").eq("series_id", series_id).eq("episode_number", ep_number).execute()
                            if not ep_id_res.data:
                                continue
                            episode_id = ep_id_res.data[0]['id']

                            # 3. سحب سيرفرات ومشاهدات الحلقة وتخزينها في episode_sources
                            server_buttons = page.locator('button, a').all()
                            is_first_server = True
                            
                            for btn in server_buttons:
                                try:
                                    if not btn.is_visible():
                                        continue
                                    btn_text = btn.text_content().strip()
                                    unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK"]
                                    if not btn_text or len(btn_text) > 15 or any(w in btn_text for w in unwanted_texts):
                                        continue
                                    
                                    btn.click(timeout=1500)
                                    time.sleep(0.5)
                                    
                                    iframe = page.locator("iframe").first
                                    if iframe.count() > 0:
                                        iframe_src = iframe.get_attribute("src")
                                        if iframe_src and "http" in iframe_src:
                                            source_payload = {
                                                "episode_id": episode_id,
                                                "quality": btn_text,
                                                "source_url": iframe_src,
                                                "is_primary": is_first_server,
                                                "source_type": "watch"
                                            }
                                            supabase.table("episode_sources").upsert(source_payload).execute()
                                            is_first_server = False
                                except:
                                    continue

                            print(f"      ✔️ تم حفظ الحلقة {ep_number} وسيرفراتها بنجاح", flush=True)

                        except Exception as ep_ex:
                            print(f"      ⚠️ خطأ في معالجة حلقة: {ep_ex}", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ في معالجة المسلسل: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_series_pages()

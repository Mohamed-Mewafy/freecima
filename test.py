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
    """استخراج رابط البوستر بدقة عالية"""
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
        # فتح صفحة مستقلة للملاحة الرئيسية
        page = browser.new_page()
        page.set_default_timeout(60000)

        page_num = 1
        print("\n🚀 === بدء السحب الشامل (استخراج كل سيرفرات المشاهدة + البوستر) ===", flush=True)

        while True:
            print(f"\n🔄 جاري فحص صفحة المسلسلات رقم: {page_num}", flush=True)
            url = f"{SERIES_CATEGORY_URL}?page={page_num}" if page_num > 1 else SERIES_CATEGORY_URL
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"⚠️ فشل تحميل الصفحة {page_num}، جاري التخطي...", flush=True)
                page_num += 1
                continue
            
            links = page.eval_on_selector_all('a[href*="view-serie.php"]', "elements => elements.map(e => e.href)")
            if not links:
                print(f"🏁 وصلت إلى نهاية الصفحات عند الصفحة {page_num}", flush=True)
                break

            unique_links = list(set(links))

            for link in unique_links:
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=60000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    series_title = clean_title(raw_title)
                    if not series_title:
                        continue

                    # فحص وجود المسلسل
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

                    # جلب جميع روابط الحلقات
                    episode_links = page.eval_on_selector_all('a[href*="watch.php?vid="], a[href*="play.php"]', "elements => elements.map(e => e.href)")
                    unique_episodes = list(set(episode_links))

                    # صفحة جديدة للحلقات لضمان عدم حدوث تعارض أثناء الضغط على السيرفرات
                    ep_page = browser.new_page()
                    ep_page.set_default_timeout(60000)

                    for ep_link in unique_episodes:
                        try:
                            play_url = ep_link.replace("watch.php", "play.php")
                            ep_page.goto(play_url, wait_until="domcontentloaded", timeout=60000)
                            
                            ep_raw_title = ep_page.locator('h1').first.text_content().strip() if ep_page.locator('h1').count() > 0 else "حلقة"
                            ep_number = extract_episode_number(ep_raw_title)
                            
                            # =========================================================
                            # المنطق المجرب من السكربت القديم لجلب كااااافة السيرفرات
                            # =========================================================
                            watch_servers = {}
                            streaming_links_list = []
                            primary_watch_url = ""

                            # جمع عناصر الأزرار في الصفحة
                            server_buttons = ep_page.locator('button, a, li').all()
                            
                            servers_info = []
                            unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "مشاهدة الآن", "تحميل الآن", "تحميل", "Download"]
                            
                            for btn in server_buttons:
                                try:
                                    if not btn.is_visible():
                                        continue
                                    btn_text = btn.text_content().strip()
                                    
                                    if not btn_text or len(btn_text) > 20 or any(w in btn_text for w in unwanted_texts):
                                        continue
                                        
                                    # فلترة تمنع تكرار الأزرار غير المتعلقة بالسيرفرات
                                    servers_info.append((btn, btn_text))
                                except:
                                    continue

                            # الضغط على كل سيرفر لاستخراج الـ iframe
                            for btn, s_name in servers_info:
                                try:
                                    btn.click(timeout=2000)
                                    time.sleep(0.7)  # وقت كافٍ لـ AJAX لتغيير الـ iframe
                                    
                                    iframe = ep_page.locator("iframe").first
                                    if iframe.count() > 0:
                                        iframe_src = iframe.get_attribute("src") or iframe.get_attribute("data-src")
                                        if iframe_src and "http" in iframe_src:
                                            # استبعاد الإعلانات
                                            if not any(bad in iframe_src.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com"]):
                                                # تنظيف اسم السيرفر
                                                clean_server_name = s_name.replace("\n", " ").strip()
                                                watch_servers[clean_server_name] = iframe_src
                                                
                                                if iframe_src not in streaming_links_list:
                                                    streaming_links_list.append(iframe_src)
                                                
                                                if not primary_watch_url:
                                                    primary_watch_url = iframe_src
                                except Exception:
                                    continue

                            # احتياطي: في حال لم يضغط على زر
                            if not primary_watch_url:
                                iframe = ep_page.locator("iframe").first
                                if iframe.count() > 0:
                                    primary_watch_url = iframe.get_attribute("src") or ""
                                    if primary_watch_url and primary_watch_url not in streaming_links_list:
                                        streaming_links_list.append(primary_watch_url)

                            # بناء البيانات
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
                            print(f"   ↳ الحلقة {ep_number}: تم جلب {len(watch_servers)} سيرفر مشاهدة ({', '.join(watch_servers.keys())})", flush=True)

                        except Exception as ep_err:
                            print(f"⚠️ خطأ بالحلقة: {ep_err}", flush=True)
                            continue
                    
                    ep_page.close()

                except Exception as e:
                    print(f"⚠️ خطأ بالمسلسل: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_series()

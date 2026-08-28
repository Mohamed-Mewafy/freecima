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
    """استخراج رابط البوستر بدقة من وسوم الصورة أو خلفيات الـ CSS"""
    try:
        # 1. البحث في عناصر الصور الخاصة بالبوستر أو الغلاف
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

        # 2. البحث في خلفيات الـ CSS (Background Image)
        bg_element = page.locator('[style*="background-image"]').first
        if bg_element.count() > 0:
            style = bg_element.get_attribute('style') or ''
            bg_match = re.search(r'url\((.*?)\)', style)
            if bg_match:
                clean_url = bg_match.group(1).replace("'", "").replace('"', "")
                if 'http' in clean_url:
                    return clean_url

        # 3. الاعتماد على og:image كخيار أخير مع التصفية
        meta_img = page.locator('meta[property="og:image"]').get_attribute("content")
        if meta_img and 'http' in meta_img and not any(bad in meta_img for bad in ['logo', 'icon', 'default']):
            return meta_img
    except Exception:
        pass
    return ""

def extract_all_servers(page):
    """الضغط على كافة السيرفرات المتاحة واستخراج الروابط المباشرة"""
    watch_servers = {}
    streaming_links_list = []
    
    # تحديد محددات أزرار/عناصر السيرفرات الشائعة في الموقع
    server_elements = page.locator('.servers-list li, .watch-servers li, ul.servers-list button, .server-btn, ul#serversNav li').all()
    
    if not server_elements:
        server_elements = page.locator('button, a[data-url], li[data-link]').all()

    for idx, el in enumerate(server_elements):
        try:
            if not el.is_visible():
                continue

            btn_text = el.text_content().strip()
            # استبعاد الأزرار الجانبية أو أزرار القوائم
            unwanted = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK", "تحميل", "Download"]
            if not btn_text or len(btn_text) > 25 or any(w in btn_text for w in unwanted):
                continue

            # في حال لم يكن للسيرفر اسم واضح، يتم تسميته رقمياً
            server_name = btn_text if len(btn_text) > 1 else f"سيرفر {idx + 1}"

            # النقر على السيرفر لتوليد الـ Iframe
            el.click(timeout=2000)
            time.sleep(0.8) # انتظار بسيط لاستجابة الـ AJAX

            # البحث عن الـ Iframe الناتج
            iframes = page.locator("iframe").all()
            for iframe in iframes:
                try:
                    src = iframe.get_attribute("src") or iframe.get_attribute("data-src")
                    if src and "http" in src:
                        # فلترة الإعلانات والملفات البرمجية الوهمية
                        if not any(bad in src.lower() for bad in ["vast.js", "provider.hlsjs.js", "audinifer.com", "googleads", "doubleclick"]):
                            if server_name not in watch_servers:
                                watch_servers[server_name] = src
                            if src not in streaming_links_list:
                                streaming_links_list.append(src)
                except Exception:
                    continue
        except Exception:
            continue

    return watch_servers, streaming_links_list

def crawl_series(context):
    print("\n🚀 === بدء السحب الذكي (إصلاح البوستر واستخراج كافة السيرفرات) ===", flush=True)
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
                print(f"      ✔️ تمت إضافة الحلقات وبداخلها ({len(watch_servers)}) سيرفر مشاهدة.", flush=True)

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

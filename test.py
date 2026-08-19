import os
import re
import time
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"

def clean_title(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|\d{4})'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[:\-]', '', clean)
    return " ".join(clean.split())

def extract_year(title):
    match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
    return int(match.group(1)) if match else None

def crawl_pages_sequentially():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(60000)

        page_num = 1
        while True:
            print(f"🔄 جاري فحص وسحب الصفحة رقم: {page_num}", flush=True)
            url = f"{CATEGORY_URL}&page={page_num}"
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"⚠️ فشل تحميل الصفحة {page_num}، جاري إعادة المحاولة...", flush=True)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as inner_e:
                    print(f"❌ تخطي الصفحة بسبب خطأ في الشبكة: {inner_e}", flush=True)
                    page_num += 1
                    continue
            
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            if not links or len(links) == 0:
                print(f"🏁 وصلت إلى نهاية الصفحات (الصفحة {page_num} فارغة). تم الانتهاء بنجاح!", flush=True)
                break

            unique_links = list(set(links))
            print(f"📄 وُجد {len(unique_links)} فيلم في الصفحة {page_num}", flush=True)

            for link in unique_links:
                try:
                    play_url = link.replace("watch.php", "play.php")
                    download_page_url = link.replace("watch.php", "download.php")
                    
                    page.goto(play_url, wait_until="domcontentloaded", timeout=60000)
                    
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    title = clean_title(raw_title)
                    year = extract_year(raw_title)
                    
                    rating = "غير متوفر"
                    rating_el = page.locator('text=/\\d\\.\\d\\/10/').first
                    if rating_el.count() > 0:
                        rating = rating_el.text_content().strip()
                    
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()

                    # =========================================================================
                    # استهداف دقيق لأزرار سيرفرات المشاهدة فقط (واستبعاد أزرار الإغلاق وتسجيل الدخول)
                    # =========================================================================
                    watch_servers = {}
                    primary_watch_url = ""
                    
                    try:
                        # البحث عن الأزرار الموجودة داخل منطقة العرض فقط وتصفية الكلمات غير المرغوبة
                        server_buttons = page.locator('button, a').all()
                        
                        servers_info = []
                        for btn in server_buttons:
                            try:
                                if not btn.is_visible():
                                    continue
                                btn_text = btn.text_content().strip()
                                # استبعاد الأزرار العامة مثل تسجيل الدخول، إغلاق، البحث، إلخ
                                unwanted_texts = ["تسجيل", "دخول", "Close", "×", "بحث", "Sign", "Register", "OK"]
                                if not btn_text or len(btn_text) > 15 or any(w in btn_text for w in unwanted_texts):
                                    continue
                                    
                                # التأكد أن الزر يقع بالقرب من منطقة المشاهدة أو الـ iframe
                                servers_info.append((btn, btn_text))
                            except:
                                continue

                        # النقر على كل سيرفر واستخراج رابط الـ iframe المرتبط به
                        for btn, s_name in servers_info:
                            try:
                                btn.click(timeout=2000)
                                time.sleep(0.7) # انتظار استجابة السيرفر وتغيير الـ iframe
                                
                                iframe = page.locator("iframe").first
                                if iframe.count() > 0:
                                    iframe_src = iframe.get_attribute("src")
                                    if iframe_src and "http" in iframe_src:
                                        watch_servers[s_name] = iframe_src
                                        if not primary_watch_url:
                                            primary_watch_url = iframe_src
                            except Exception as click_ex:
                                # تجاوز أي زر يفشل في النقر دون توقف السكربت
                                continue
                                
                    except Exception as ex:
                        print(f"⚠️ خطأ أثناء تتبع سيرفرات المشاهدة: {ex}")

                    # احتياطي: لو لم يتم التقاط أزرار، خذ رابط الـ iframe الافتراضي
                    if not primary_watch_url:
                        iframe = page.locator("iframe").first
                        if iframe.count() > 0:
                            primary_watch_url = iframe.get_attribute("src") or ""

                    # سحب سيرفرات التحميل
                    download_links = {}
                    try:
                        page.goto(download_page_url, wait_until="domcontentloaded", timeout=45000)
                        all_download_anchors = page.eval_on_selector_all(
                            'a', 
                            "elements => elements.map(e => ({text: e.innerText.trim(), href: e.href}))"
                        )
                        
                        unwanted_keywords = [
                            "category.php", "watch.php", "play.php", "register.php", 
                            "login.php", "movies.php", "episodes.php", "newvideos.php", 
                            "topvideos.php", "moslslat.php", "#", "javascript"
                        ]
                        
                        for item in all_download_anchors:
                            href = item['href']
                            txt = item['text']
                            is_unwanted = any(keyword in href for keyword in unwanted_keywords)
                            
                            if href and not is_unwanted and "cfree.icu" not in href and "cima.today" not in href and ("http" in href or "magnet" in href):
                                server_name = txt.split('\n')[0] if txt else "Server"
                                download_links[server_name] = href
                    except Exception as ex:
                        print(f"⚠️ تعذر سحب روابط التحميل لهذا الفيلم: {ex}")

                    poster_url = ""
                    meta_img = page.locator('meta[property="og:image"]')
                    if meta_img.count() > 0:
                        poster_url = meta_img.get_attribute("content") or ""

                    direct_links_payload = {
                        "primary_watch": primary_watch_url,
                        "watch_servers": watch_servers,
                        "download_servers": download_links
                    }

                    movie_payload = {
                        "title": title,
                        "watch_url": play_url,  
                        "poster_url": poster_url,
                        "year": year,
                        "description": description,
                        "rating": rating,
                        "direct_links": direct_links_payload
                    }

                    supabase.table("arabic_movies").upsert(movie_payload, on_conflict="title").execute()
                    print(f"🔄 تم تحديث السيرفرات بالكامل وحفظ الفيلم: {title} (عدد السيرفرات: {len(watch_servers)})", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_pages_sequentially()

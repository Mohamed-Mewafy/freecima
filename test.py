import json
import time
from playwright.sync_api import sync_playwright

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"
JSON_FILE = "arabic_movies.json"

def get_server_url(page):
    try:
        iframe = page.locator("iframe").first
        if iframe.count() > 0:
            return iframe.get_attribute("src")
    except:
        pass
    return None

def crawl_with_playwright():
    movies_data = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for page_num in range(1, 2):  # صفحة واحدة للتجربة
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            for link in list(set(links))[:5]: # أول 5 أفلام
                try:
                    play_url = link.replace("watch.php", "play.php")
                    page.goto(play_url, wait_until="networkidle")
                    
                    # 1. العنوان
                    title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    
                    # 2. رابط السيرفر
                    server_url = get_server_url(page)
                    
                    # 3. جلب رابط البوستر (الـ poster الخاص بالفيلم)
                    poster_url = ""
                    # البحث عن الصورة البارزة في منطقة بوستر الفيلم أو الحاويات الخاصة به
                    poster_locators = ['.poster img', '.movie-poster img', '.single-poster img', 'div.poster img', '.details img']
                    for loc in poster_locators:
                        img_el = page.locator(loc).first
                        if img_el.count() > 0:
                            src = img_el.get_attribute("src") or img_el.get_attribute("data-src")
                            if src:
                                if not src.startswith('http'):
                                    poster_url = BASE_DOMAIN + "/" + src.lstrip('/')
                                else:
                                    poster_url = src
                                break

                    # 4. جلب القصة الحقيقية للفيلم وتجنب رسائل السيرفر العامة
                    description = "لا يوجد وصف"
                    p_locators = ['.story p', '.movie-story p', '.desc p', 'div.story', 'p']
                    for loc in p_locators:
                        elements = page.locator(loc)
                        for i in range(elements.count()):
                            txt = elements.nth(i).text_content().strip()
                            # نتأكد أن النص هو قصة الفيلم وليس رسالة السيرفر التلقائية
                            if len(txt) > 40 and "اذا كان السيرفر" not in txt and "مشاهدة وتحميل" not in txt:
                                description = txt
                                break
                        if description != "لا يوجد وصف":
                            break

                    movie_info = {
                        "title": title,
                        "watch_url": play_url,
                        "server_url": server_url,
                        "poster_url": poster_url,
                        "description": description,
                        "rating": "غير متوفر"
                    }
                    
                    movies_data.append(movie_info)
                    print(f"✅ تم سحب: {title}", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
        
        browser.close()

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("🎉 تم الحفظ بنجاح!")

if __name__ == "__main__":
    crawl_with_playwright()

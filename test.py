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
                    
                    # 3. رابط البوستر الحقيقي (البحث عن الصورة داخل تفاصيل الفيلم وليس الشعار العام)
                    poster_url = ""
                    # محاولة جلب الصورة البارزة للفيلم
                    poster_element = page.locator('.story img, .poster img, .movie-img img, .details img').first
                    if poster_element.count() > 0:
                        poster_url = poster_element.get_attribute("src") or poster_element.get_attribute("data-src") or ""
                        if poster_url and not poster_url.startswith('http'):
                            poster_url = BASE_DOMAIN + "/" + poster_url.lstrip('/')

                    # 4. القصة أو الوصف الحقيقي (البحث عن فقرة القصة في صفحة الفيلم)
                    description = "لا يوجد وصف"
                    # عادة ما تكون القصة داخل div يصف قصة الفيلم أو فقرة تفصيلية
                    desc_elements = page.locator('p')
                    for i in range(desc_elements.count()):
                        txt = desc_elements.nth(i).text_content().strip()
                        if "قصة الفيلم" in txt or "تدور الأحداث" in txt or len(txt) > 50:
                            description = txt
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
                    print(f"✅ تم سحب بيانات: {title}", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
        
        browser.close()

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("🎉 تم التحديث والحفظ بنجاح!")

if __name__ == "__main__":
    crawl_with_playwright()

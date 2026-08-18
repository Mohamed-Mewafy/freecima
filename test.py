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

        for page_num in range(1, 2):  # صفحة واحدة للتجربة (يمكنك زيادتها)
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            for link in list(set(links))[:5]: # أول 5 أفلام للتجربة
                try:
                    play_url = link.replace("watch.php", "play.php")
                    page.goto(play_url, wait_until="networkidle")
                    
                    # 1. العنوان
                    title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    
                    # 2. رابط السيرفر
                    server_url = get_server_url(page)
                    
                    # 3. رابط البوستر (الصورة)
                    poster_url = ""
                    poster_element = page.locator('.poster img, .movie-poster img, img').first
                    if poster_element.count() > 0:
                        poster_url = poster_element.get_attribute("src") or poster_element.get_attribute("data-src") or ""
                        if poster_url and not poster_url.startswith('http'):
                            poster_url = BASE_DOMAIN + "/" + poster_url.lstrip('/')

                    # 4. القصة أو الوصف
                    description = "لا يوجد وصف"
                    desc_element = page.locator('.story, .desc, .movie-story, p').first
                    if desc_element.count() > 0:
                        description = desc_element.text_content().strip()

                    # 5. التقييم (إن وجد في الصفحة)
                    rating = "غير متوفر"
                    rating_element = page.locator('.rating, .rate, span.score').first
                    if rating_element.count() > 0:
                        rating = rating_element.text_content().strip()

                    movie_info = {
                        "title": title,
                        "watch_url": play_url,
                        "server_url": server_url,
                        "poster_url": poster_url,
                        "description": description,
                        "rating": rating
                    }
                    
                    movies_data.append(movie_info)
                    print(f"✅ تم سحب التفاصيل لـ: {title}", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ خطأ في معالجة فيلم: {e}", flush=True)
        
        browser.close()

    # حفظ النتائج في ملف الـ JSON
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("🎉 تم حفظ جميع البيانات بنجاح!")

if __name__ == "__main__":
    crawl_with_playwright()

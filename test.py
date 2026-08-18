import json
import time
from playwright.sync_api import sync_playwright

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"
JSON_FILE = "arabic_movies.json"

def get_server_url(page):
    # محاولة إيجاد رابط السيرفر داخل الـ iframe أو المشغل
    try:
        # البحث عن أي iframe قد يحتوي على رابط الفيديو
        iframe = page.locator("iframe").first
        if iframe.count() > 0:
            return iframe.get_attribute("src")
    except:
        pass
    return None

def crawl_with_playwright():
    movies_data = []
    
    with sync_playwright() as p:
        # تشغيل المتصفح في وضع headless (ضروري لـ GitHub Actions)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for page_num in range(1, 2):  # صفحة واحدة للتجربة
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            
            # استخراج روابط الأفلام
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            for link in list(set(links))[:5]: # أول 5 أفلام للتجربة
                try:
                    play_url = link.replace("watch.php", "play.php")
                    page.goto(play_url, wait_until="networkidle")
                    
                    # استخراج البيانات
                    title = page.locator('h1').first.text_content().strip()
                    server_url = get_server_url(page)
                    
                    movie_info = {
                        "title": title,
                        "watch_url": play_url,
                        "server_url": server_url
                    }
                    
                    movies_data.append(movie_info)
                    print(f"✅ تم سحب: {title} | الرابط: {server_url}", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ خطأ في فيلم: {e}")
        
        browser.close()

    # حفظ الملف
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    crawl_with_playwright()

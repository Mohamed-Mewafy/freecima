import json
import re
from playwright.sync_api import sync_playwright

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"
JSON_FILE = "arabic_movies.json"

def clean_title(title):
    # إزالة الكلمات الزائدة
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|\d{4})'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    # إزالة المسافات الزائدة والرموز المتبقية
    clean = re.sub(r'[:\-]', '', clean)
    return " ".join(clean.split())

def crawl_with_playwright():
    movies_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for page_num in range(1, 2):
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            for link in list(set(links))[:5]:
                try:
                    play_url = link.replace("watch.php", "play.php")
                    page.goto(play_url, wait_until="networkidle")
                    
                    # 1. العنوان الصافي
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    title = clean_title(raw_title)
                    
                    # 2. التقييم
                    rating = "غير متوفر"
                    rating_el = page.locator('span:has-text("/10")').first
                    if rating_el.count() > 0:
                        rating = rating_el.text_content().strip()
                    
                    # 3. الوصف
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story, .details, p:has-text("مشاهدة وتحميل") + p').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()
                        
                    # 4. رابط السيرفر
                    iframe = page.locator("iframe").first
                    server_url = iframe.get_attribute("src") if iframe.count() > 0 else "غير متوفر"

                    movies_data.append({
                        "title": title,
                        "watch_url": play_url,
                        "server_url": server_url,
                        "description": description,
                        "rating": rating
                    })
                    print(f"✅ تمت معالجة: {title}", flush=True)
                except Exception as e:
                    print(f"⚠️ خطأ: {e}")
        browser.close()

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    crawl_with_playwright()

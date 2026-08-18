import os
import re
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

# سحب المفاتيح بأمان من متغيرات البيئة في GitHub Secrets
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

def crawl_and_save_to_supabase():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for page_num in range(1, 2):  # يمكنك تعديل عدد الصفحات حسب رغبتك
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            for link in list(set(links))[:5]:  # عينة أول 5 أفلام للتجربة
                try:
                    play_url = link.replace("watch.php", "play.php")
                    page.goto(play_url, wait_until="networkidle")
                    
                    # 1. العنوان الصافي والسنة
                    raw_title = page.locator('h1').first.text_content().strip() if page.locator('h1').count() > 0 else "بدون عنوان"
                    title = clean_title(raw_title)
                    year = extract_year(raw_title)
                    
                    # 2. التقييم
                    rating = "غير متوفر"
                    rating_el = page.locator('text=/\\d\\.\\d\\/10/').first
                    if rating_el.count() > 0:
                        rating = rating_el.text_content().strip()
                    
                    # 3. الوصف
                    description = "لا يوجد وصف"
                    desc_el = page.locator('.story').first
                    if desc_el.count() > 0:
                        description = desc_el.text_content().strip()
                        
                    # 4. رابط السيرفر المباشر (سيتم وضعه مباشرة في watch_url)
                    iframe = page.locator("iframe").first
                    server_url = iframe.get_attribute("src") if iframe.count() > 0 else ""

                    # 5. البوستر
                    poster_url = ""
                    meta_img = page.locator('meta[property="og:image"]')
                    if meta_img.count() > 0:
                        poster_url = meta_img.get_attribute("content") or ""

                    # تجهيز البيانات (watch_url أصبح يحمل رابط السيرفر المباشر)
                    movie_payload = {
                        "title": title,
                        "watch_url": server_url,  
                        "poster_url": poster_url,
                        "year": year,
                        "description": description,
                        "rating": rating,
                        "direct_links": {"original_page": play_url}
                    }

                    # الإدراج في جدول arabic_movies في Supabase
                    response = supabase.table("arabic_movies").upsert(movie_payload, on_conflict="watch_url").execute()
                    print(f"✅ تم الحفظ بنجاح: {title}", flush=True)

                except Exception as e:
                    print(f"⚠️ خطأ في معالجة الفيلم: {e}", flush=True)
                    
        browser.close()

if __name__ == "__main__":
    crawl_and_save_to_supabase()

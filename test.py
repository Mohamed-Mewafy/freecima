import os
import re
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ يرجى التأكد من ضبط SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_title_strict(title):
    # إزالة اسم ماي سيما بجميع صيغ كتابته
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا|ماي\s*سيما|مايسيما|وي\s*سيما|ويسيما|mycima|cima)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def get_best_poster_deep(page, base_url):
    try:
        # 1. فحص meta og:image
        meta_img = page.locator('meta[property="og:image"]').get_attribute("content")
        if meta_img and not any(bad in meta_img.lower() for bad in ['logo', 'icon', 'default', 'banner']):
            return urljoin(base_url, meta_img.strip())

        # 2. فحص صور البوسترات عبر السمات المباشرة والكسولة
        img_locators = page.locator('.Poster img, .poster img, .image img, .single-poster img, .movie-image img, article img').all()
        for img in img_locators:
            for attr in ['data-src', 'data-lazy-src', 'data-original', 'src']:
                val = img.get_attribute(attr)
                if val:
                    candidate = val.strip().split()[0]
                    if candidate and not any(bad in candidate.lower() for bad in ['logo', 'avatar', 'icon', 'svg', 'data:image']):
                        return urljoin(base_url, candidate)

        # 3. فحص الخلفيات background-image
        bg_elements = page.locator('.Poster, .poster, [style*="background-image"]').all()
        for bg in bg_elements:
            style = bg.get_attribute('style') or ''
            match = re.search(r'url\([\'"]?(.*?)[\'"]?\)', style)
            if match:
                candidate = match.group(1).strip()
                if candidate and not any(bad in candidate.lower() for bad in ['logo', 'icon', 'default']):
                    return urljoin(base_url, candidate)
    except Exception:
        pass
    return ""

def fix_existing_movies():
    # جلب جميع الأفلام الموجودة حالياً
    response = supabase.table("movies_cima").select("id, title, watch_url, poster_url").execute()
    movies = response.data or []
    
    print(f"🔄 جاري فحص وتحديث {len(movies)} فيلم في قاعدة البيانات...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        for movie in movies:
            movie_id = movie["id"]
            current_title = movie.get("title", "")
            watch_url = movie.get("watch_url")
            current_poster = movie.get("poster_url")

            # تنظيف العنوان
            new_title = clean_title_strict(current_title)
            new_poster = current_poster

            # إذا كان البوستر مفقوداً والرابط موجود
            if (not current_poster or "http" not in current_poster) and watch_url:
                try:
                    page.goto(watch_url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(0.8) # مهلة بسيطة لاكتمال تحميل الـ lazy-load
                    
                    # استخراج العنوان الأصلي من الصفحة إذا كان العنوان الحالي بحاجة لتصحيح إضافي
                    h1_el = page.locator('h1').first
                    if h1_el.count() > 0:
                        raw_h1 = h1_el.text_content().strip()
                        new_title = clean_title_strict(raw_h1)

                    new_poster = get_best_poster_deep(page, watch_url)
                except Exception as e:
                    print(f"⚠️ تعذر فتح {watch_url}: {e}", flush=True)

            # تجهيز حقول التحديث
            update_data = {}
            if new_title and new_title != current_title:
                update_data["title"] = new_title

            if new_poster and new_poster != current_poster:
                update_data["poster_url"] = new_poster

            if update_data:
                supabase.table("movies_cima").update(update_data).eq("id", movie_id).execute()
                print(f"✔️ تم تحديث: {new_title} | البوستر: {'تم الإصلاح' if 'poster_url' in update_data else 'لم يتغير'}", flush=True)
            else:
                print(f"⏭️ سليم دون تعديل: {current_title}", flush=True)

        browser.close()
        print("✨ اكتملت مراجعة وتحديث جميع البيانات بنجاح!", flush=True)

if __name__ == "__main__":
    fix_existing_movies()

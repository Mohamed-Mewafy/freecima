import os
import re
import urllib.parse
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# مفتاح TMDB API المجاني المباشر
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "b6b668045bb658eb025ed996abcb0f56")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ يرجى التأكد من ضبط SUPABASE_URL و SUPABASE_KEY في متغيرات البيئة.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_title_strict(title):
    pattern = r'(مشاهدة|فيلم|مسلسل|كامل|اون لاين|HD|1080p|720p|4K|مترجم|مدبلج|حصريا|ماي\s*سيما|مايسيما|وي\s*سيما|ويسيما|mycima|cima)'
    clean = re.sub(pattern, '', title, flags=re.IGNORECASE)
    clean = re.sub(r'[\(\)\[\]\{\}\:\-\|\،]', ' ', clean)
    clean = re.sub(r'\b(20\d{2}|19\d{2})\b', '', clean)
    return " ".join(clean.split()).strip()

def fetch_poster_from_tmdb(title):
    """جلب بوستر رسمي عالي الدقة عبر TMDB"""
    try:
        query = urllib.parse.quote(title)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&language=ar"
        res = requests.get(url, timeout=10).json()
        results = res.get("results", [])
        
        # إن لم يجد باللغة العربية نبحث باللغة الأصلية
        if not results:
            url_en = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
            res = requests.get(url_en, timeout=10).json()
            results = res.get("results", [])

        if results and results[0].get("poster_path"):
            poster_path = results[0]["poster_path"]
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
    except Exception:
        pass
    return ""

def fix_all_movies():
    print("🚀 جاري جلب جميع الأفلام من قاعدة البيانات لتصحيح العناوين والبوسترات...", flush=True)
    response = supabase.table("movies_cima").select("id, title, poster_url").execute()
    movies = response.data or []

    print(f"📊 تم العثور على {len(movies)} فيلم، جاري المعالجة السريعة...", flush=True)

    seen_titles = set()

    for movie in movies:
        movie_id = movie["id"]
        raw_title = movie.get("title", "")
        current_poster = movie.get("poster_url") or ""

        clean_name = clean_title_strict(raw_title)
        if not clean_name:
            continue

        # إذا تكرر نفس العنوان، نحذف السجل الزائد لمنع خطأ Unique Constraint
        if clean_name in seen_titles:
            print(f"🗑️ حذف نسخة مكررة للفيلم: {clean_name} (ID: {movie_id})", flush=True)
            try:
                supabase.table("movies_cima").delete().eq("id", movie_id).execute()
            except Exception:
                pass
            continue

        seen_titles.add(clean_name)

        # جلب البوستر الجديد إذا كان مفقوداً أو صورة فارغة
        new_poster = current_poster
        if not current_poster or "image.tmdb" not in current_poster:
            tmdb_poster = fetch_poster_from_tmdb(clean_name)
            if tmdb_poster:
                new_poster = tmdb_poster

        # تجهيز التحديث
        update_data = {}
        if clean_name != raw_title:
            update_data["title"] = clean_name
        if new_poster and new_poster != current_poster:
            update_data["poster_url"] = new_poster

        if update_data:
            try:
                supabase.table("movies_cima").update(update_data).eq("id", movie_id).execute()
                p_status = "✔️ تم تحديث البوستر" if "poster_url" in update_data else "لم يتغير البوستر"
                print(f"✅ {clean_name} | {p_status}", flush=True)
            except Exception as e:
                print(f"⚠️ خطأ أثناء تحديث {clean_name}: {e}", flush=True)
        else:
            print(f"⏭️ {clean_name} | سليم دون تعديل", flush=True)

    print("\n🎉 تم الانتهاء من تحديث وتنظيف جميع البوسترات والعناوين بنجاح!", flush=True)

if __name__ == "__main__":
    fix_all_movies()

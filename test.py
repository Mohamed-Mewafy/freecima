import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"
JSON_FILE = "arabic_movies.json"

# إعداد Headers متكاملة ليبدو الطلب كأنه من متصفح حقيقي
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Referer": "https://cfree.icu/",
    "Connection": "keep-alive"
}

def clean_movie_title(raw_title):
    words_to_remove = ["مشاهدة", "فيلم", "مسلسل", "انيميشن", "مترجم", "مدبلج", "HD", "4K", "1080p", "720p"]
    for word in words_to_remove:
        raw_title = re.sub(rf'\b{word}\b', '', raw_title, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', raw_title).strip()

def save_movie_to_json(movie_data):
    data = []
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = []
            
    if not any(m.get('watch_url') == movie_data['watch_url'] for m in data):
        data.append(movie_data)
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f" 💾 [تم الحفظ في JSON]: {movie_data['clean_title']}")

def crawl_cfree():
    print("🚀 بدء السحب باستخدام الطلبات المباشرة (Requests + Custom Headers)...")
    
    for page_num in range(1, 3):
        url = f"{CATEGORY_URL}&page={page_num}"
        print(f"\n--- فحص الصفحة {page_num} ---")
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f" ❌ خطأ في الاتصال بالسيرفر، الكود: {response.status_code}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            movie_links = set()
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if 'watch.php?vid=' in href:
                    full_link = href if href.startswith('http') else BASE_DOMAIN + "/" + href.lstrip('/')
                    movie_links.add(full_link)
                    
            print(f"تم العثور على {len(movie_links)} رابط في هذه الصفحة.")
            
            for link in movie_links:
                try:
                    play_url = link.replace("watch.php", "play.php")
                    movie_res = requests.get(play_url, headers=HEADERS, timeout=15)
                    if movie_res.status_code != 200:
                        continue
                        
                    movie_soup = BeautifulSoup(movie_res.text, 'html.parser')
                    
                    title_elem = movie_soup.select_one('h1') or movie_soup.select_one('title')
                    title = title_elem.text.strip() if title_elem else "بدون عنوان"
                    
                    poster_img = movie_soup.select_one('.poster img') or movie_soup.select_one('img')
                    poster = ""
                    if poster_img:
                        poster = poster_img.get('data-src') or poster_img.get('src') or ""
                        if poster and not poster.startswith('http'):
                            poster = BASE_DOMAIN + "/" + poster.lstrip('/')

                    desc_elem = movie_soup.select_one('.story') or movie_soup.select_one('p')
                    desc = desc_elem.text.strip() if desc_elem else "لا يوجد وصف"
                    
                    movie_info = {
                        "title": title,
                        "clean_title": clean_movie_title(title),
                        "watch_url": play_url,
                        "poster_url": poster,
                        "description": desc,
                        "category_type": "أفلام عربية"
                    }
                    
                    save_movie_to_json(movie_info)
                    time.sleep(1.5)
                except Exception as e:
                    print(f" ⚠️ خطأ أثناء معالجة الفيلم: {e}")
                    
        except Exception as e:
            print(f" ❌ خطأ في فتح الصفحة: {e}")

    print("\n🎉 تم الانتهاء وحفظ النتائج بنجاح!")

if __name__ == "__main__":
    crawl_cfree()
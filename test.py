import os
import re
import time
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

# إعدادات Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DOMAIN = "https://cfree.icu"
CATEGORY_URL = f"{BASE_DOMAIN}/category.php?cat=arabic-moives"

# ... (دوال clean_title و extract_year كما هي) ...

def crawl_all_pages():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page_num = 1
        while True:  # حلقة لا نهائية
            print(f"🔄 جاري العمل على الصفحة رقم: {page_num}", flush=True)
            url = f"{CATEGORY_URL}&page={page_num}"
            page.goto(url, wait_until="networkidle")
            
            # التحقق من وجود أفلام في الصفحة
            links = page.eval_on_selector_all('a[href*="watch.php?vid="]', "elements => elements.map(e => e.href)")
            
            # إذا لم نجد روابط، يعني وصلنا لآخر صفحة، نعيد من الأول
            if not links:
                print("🏁 انتهت الصفحات، إعادة البدء من الصفحة 1...", flush=True)
                page_num = 1
                time.sleep(60) # انتظر دقيقة قبل البدء من جديد لتقليل الضغط
                continue

            for link in list(set(links)): # سحب كل الروابط في الصفحة
                try:
                    # (هنا يوضع كود معالجة الفيلم الذي كتبناه سابقاً...)
                    # ملاحظة: تأكد من وضع logic السحب هنا
                    pass 
                except Exception as e:
                    print(f"⚠️ خطأ: {e}", flush=True)
            
            page_num += 1
            
        browser.close()

if __name__ == "__main__":
    crawl_all_pages()

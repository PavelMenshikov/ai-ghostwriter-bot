from duckduckgo_search import DDGS
import re

BLACKLIST = [
    "wikipedia.org", "scmp.com", "cnn.com", "bbc.com", "nytimes.com", 
    "pogoda", "weather", "accuweather", "gismeteo", "coindesk.com/markets", 
    "investing.com/crypto"
]

def search_internet(query, region="us-en", max_results=8):
    print(f"🔎 DDGS Гуглит: '{query}' [Region: {region}]...")
    text_summary = ""
    
    try:
        
        results = DDGS().text(
            keywords=query, 
            region=region, 
            safesearch="off", 
            timelimit="d", 
            max_results=max_results
        )
        
        if not results:
            print("❌ Пусто. Попробуй расширить запрос.")
            return None

        valid_count = 0
        for res in results:
            title = res.get('title', '')
            body = res.get('body', '')
            url = res.get('href', '')
            
           
            if any(bad in url for bad in BLACKLIST): continue
            
           
            if bool(re.search(r'[\u4e00-\u9fff]', title)): continue

          
            if len(body) < 40: continue

            text_summary += (
                f"TITLE: {title}\n"
                f"SUMMARY: {body}\n"
                f"LINK: {url}\n"
                f"----------------\n"
            )
            valid_count += 1
            
        print(f"✅ Найдено {valid_count} свежих статей.")
        return text_summary if valid_count > 0 else None

    except Exception as e:
        print(f"❌ Ошибка поиска DDGS: {e}")
        return None
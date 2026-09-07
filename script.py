import xml.etree.ElementTree as ET
import requests

# Исходная ссылка на фид из Пром
PROM_FEED_URL = "https://plumbershop.in.ua/rozetka_feed.xml?rozetka_hash_tag=c69c98092d7af42c4a6369d81"
OUTPUT_FILE = "rozetka_clean.xml"

def process_feed():
    response = requests.get(PROM_FEED_URL, timeout=60)
    response.raise_for_status()
    
    root = ET.fromstring(response.content)
    
    for offer in root.findall(".//offer"):
        article_elem = offer.find("article")
        article = article_elem.text.strip() if article_elem is not None and article_elem.text else ""
        
        # Если артикул НЕ начинается с "SD" (товар не от Sandi+), убираем скидку Пром
        if not article.startswith("SD"):
            price_elem = offer.find("price")
            price_old_elem = offer.find("price_old")
            
            if price_old_elem is not None and price_old_elem.text:
                if price_elem is not None:
                    price_elem.text = price_old_elem.text  # Восстанавливаем цену без скидки
                offer.remove(price_old_elem)  # Удаляем зачеркнутую цену для Розетки

    tree = ET.ElementTree(root)
    tree.write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    process_feed()

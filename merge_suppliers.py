import os
import xml.etree.ElementTree as ET
import requests
from datetime import datetime

FEED_URLS = [
    "https://b2b-sandi.com.ua/ru/export/view/518ff4f405eb0e0c32bd56bb365bc210-784-1712587389/yml_prom",
    "https://b2b.valeso.ua/data/f0db8dbb55bd1610efe71fc5de37b972.xml",
    "https://rs4u.com.ua/ua/cabinet/price/get?id=a924d145d45bdc58901689ec6299f6fb",
    "https://b2b-sklad.com/price/4452/ru/1/0/xml/export.xml",
    "https://back-prod.olinfrastructure.com/b2b/product-export/file/9E4F1743-7346-40D6-8AB9-422474591DA1/xml"
]

OUTPUT_FILE = "merged_prom_catalog.xml"

# Корректировки цен по артикулам: {"АРТИКУЛ": "НОВАЯ_ЦЕНА"}
CUSTOM_PRICES = {
    "ТР-00027103": "350"
}

def merge_feeds():
    yml_catalog = ET.Element("yml_catalog", date=datetime.now().strftime("%Y-%m-%d %H:%M"))
    shop = ET.SubElement(yml_catalog, "shop")
    
    ET.SubElement(shop, "name").text = "PlumberShop Suppliers Catalog"
    ET.SubElement(shop, "company").text = "Сантехник"
    
    currencies_elem = ET.SubElement(shop, "currencies")
    categories_elem = ET.SubElement(shop, "categories")
    offers_elem = ET.SubElement(shop, "offers")
    
    added_currencies = set()
    seen_offer_ids = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    skipped_zero_prices = 0
    skipped_duplicate_offers = 0

    for idx, url in enumerate(FEED_URLS, start=1):
        cache_file = f"cache_s{idx}.xml"
        xml_content = None
        
        print(f"[{idx}/5] Загрузка фида: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            xml_content = response.content
            
            with open(cache_file, "wb") as f:
                f.write(xml_content)
            print(f"   -> Успешно скачано и обновлено в кэше ({cache_file}).")
        except Exception as e:
            print(f"   [ВНИМАНИЕ] Сервер поставщика #{idx} недоступен: {e}")
            if os.path.exists(cache_file):
                print(f"   -> Загружаем данные из локального кэша: {cache_file}")
                with open(cache_file, "rb") as f:
                    xml_content = f.read()
            else:
                print(f"   [ОШИБКА] Кэш {cache_file} отсутствует, пропуск.")
                continue

        if not xml_content:
            continue

        try:
            root = ET.fromstring(xml_content)
            shop_source = root.find("shop") if root.find("shop") is not None else root
            
            # 1. Валюты
            currencies_source = shop_source.find("currencies")
            if currencies_source is not None:
                for curr in currencies_source.findall("currency"):
                    curr_id = curr.attrib.get("id")
                    if curr_id and curr_id not in added_currencies:
                        added_currencies.add(curr_id)
                        ET.SubElement(currencies_elem, "currency", curr.attrib)
            
            # 2. Категории с изоляцией ID (чтобы структуры категорий разных поставщиков не смешивались)
            categories_source = shop_source.find("categories")
            if categories_source is not None:
                for cat in categories_source.findall("category"):
                    orig_id = cat.attrib.get("id")
                    new_id = f"c{idx}_{orig_id}"
                    
                    new_cat_attrib = dict(cat.attrib)
                    new_cat_attrib["id"] = new_id
                    
                    if "parentId" in new_cat_attrib:
                        new_cat_attrib["parentId"] = f"c{idx}_{new_cat_attrib['parentId']}"
                    
                    new_cat = ET.SubElement(categories_elem, "category", new_cat_attrib)
                    new_cat.text = cat.text
            
            # 3. Товары (offers)
            offers_source = shop_source.find("offers")
            if offers_source is not None:
                for offer in offers_source.findall("offer"):
                    # Проверка корректности цены (отфильтровываем товары с ценой менее 0.01 грн)
                    price_elem = offer.find("price")
                    price_val = 0.0
                    if price_elem is not None and price_elem.text:
                        try:
                            price_val = float(price_elem.text.replace(",", ".").strip())
                        except ValueError:
                            price_val = 0.0

                    if price_val < 0.01:
                        skipped_zero_prices += 1
                        continue

                    # Сохраняем ОРИГИНАЛЬНЫЙ offer id без префиксов
                    offer_id = offer.attrib.get("id", "")
                    if offer_id in seen_offer_ids:
                        skipped_duplicate_offers += 1
                        continue
                    seen_offer_ids.add(offer_id)
                    
                    # Привязываем товар к изолированной категории
                    cat_id_elem = offer.find("categoryId")
                    if cat_id_elem is not None and cat_id_elem.text:
                        cat_id_elem.text = f"c{idx}_{cat_id_elem.text}"
                    
                    # Модификация цен по артикулам
                    art = (offer.findtext("article") or offer.findtext("vendorCode") or "").strip()
                    if art in CUSTOM_PRICES:
                        new_price = CUSTOM_PRICES[art]
                        if price_elem is not None:
                            price_elem.text = new_price
                        else:
                            ET.SubElement(offer, "price").text = new_price
                        print(f"   [ЦЕНА ИЗМЕНЕНА] Товар {art}: установлена цена {new_price} грн")

                    offers_elem.append(offer)

            print(f"   -> Фид #{idx} успешно добавлен в каталог.")

        except Exception as e:
            print(f"   [ОШИБКА] Разбор XML для фида #{idx} завершился с ошибкой: {e}")

    if not added_currencies:
        ET.SubElement(currencies_elem, "currency", id="UAH", rate="1")

    print(f"\nОтфильтровано позиций с нулевой/некорректной ценой: {skipped_zero_prices}")
    print(f"Пропущено повторных offer ID: {skipped_duplicate_offers}")

    tree = ET.ElementTree(yml_catalog)
    ET.indent(tree, space="  ", level=0)
    tree.write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"Объединенный файл сохранен как {OUTPUT_FILE}")

if __name__ == "__main__":
    merge_feeds()

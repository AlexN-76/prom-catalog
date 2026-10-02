import ast
import csv
import gzip
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATABASE = BASE / "prom_existing_products_safe.csv"
OLD_SCRIPT = BASE / "merge_suppliers.py"
OUTPUT = BASE / "merged_prom_catalog_test.xml"
EXCLUSIONS = BASE / "merge_exclusions_test.csv"
REPORT = BASE / "merge_summary_test.json"

SUPPLIERS = {
    1: "SANDI",
    2: "VALESO",
    3: "RS4U",
    4: "B2B-SKLAD",
    5: "OL Infrastructure",
}

MIN_RATIO = 0.70


def normalize(value):
    value = str(value or "").strip()
    if re.fullmatch(r"[0-9]+", value):
        return value.lstrip("0") or "0"
    return value


def product_code(offer):
    return (
        offer.findtext("vendorCode")
        or offer.findtext("article")
        or ""
    ).strip()


def load_config():
    tree = ast.parse(OLD_SCRIPT.read_text(encoding="utf-8"))
    config = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id in ("FEED_URLS", "CUSTOM_PRICES"):
                    config[target.id] = ast.literal_eval(node.value)

    urls = config["FEED_URLS"]
    prices = config.get("CUSTOM_PRICES", {})

    if len(urls) != 5:
        raise RuntimeError("Ожидалось ровно пять поставщиков")

    return urls, prices


def load_database():
    by_id = {}
    articles = set()

    with DATABASE.open(
        encoding="utf-8-sig", newline=""
    ) as f:
        for row in csv.DictReader(f):
            oid = (row["offer_id"] or "").strip()
            article = normalize(row["article"])

            if oid:
                if oid in by_id and by_id[oid] != article:
                    raise RuntimeError(f"Конфликт базы: {oid}")
                by_id[oid] = article

            if article:
                articles.add(article)

    return by_id, articles


def load_previous():
    candidates = [
        Path.home() / "merged_prom_catalog.xml.gz",
        BASE / "merged_prom_catalog.xml",
    ]

    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise RuntimeError(
            "Нет предыдущего XML для аварийного восстановления"
        )

    opener = gzip.open if path.suffix == ".gz" else open

    with opener(path, "rb") as f:
        root = ET.parse(f).getroot()

    shop = root.find("shop")
    if shop is None:
        raise RuntimeError("Повреждён предыдущий XML")

    old = {
        n: {"categories": [], "offers": []}
        for n in SUPPLIERS
    }

    old_currencies = shop.findall("./currencies/currency")

    for category in shop.findall("./categories/category"):
        cid = category.get("id", "")
        match = re.match(r"^c([1-5])_", cid)
        if match:
            old[int(match.group(1))]["categories"].append(category)

    unmatched = 0
    for offer in shop.findall("./offers/offer"):
        cid = (offer.findtext("categoryId") or "").strip()
        match = re.match(r"^c([1-5])_", cid)

        if match:
            old[int(match.group(1))]["offers"].append(offer)
        else:
            unmatched += 1

    if unmatched:
        raise RuntimeError(
            f"В старом XML не определён поставщик "
            f"для {unmatched} товаров"
        )

    return old, old_currencies, str(path)


def download_supplier(number, url):
    simulated = os.environ.get("SIMULATE_DOWN", "")
    if simulated == str(number):
        raise RuntimeError("Тестовая имитация недоступности")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=120) as r:
        data = r.read()

    root = ET.fromstring(data)
    shop = root.find("shop")
    if shop is None:
        shop = root

    source_categories = shop.findall("./categories/category")
    source_offers = shop.findall("./offers/offer")
    currencies = shop.findall("./currencies/currency")

    if not source_categories or not source_offers:
        raise RuntimeError("Пустой или неподходящий XML")

    category_ids = {
        c.get("id", "") for c in source_categories
    }

    categories = []
    for cat in source_categories:
        attrs = dict(cat.attrib)
        original_id = attrs.get("id")

        if not original_id:
            raise RuntimeError("Категория без ID")

        attrs["id"] = f"c{number}_{original_id}"

        if attrs.get("parentId"):
            attrs["parentId"] = (
                f"c{number}_{attrs['parentId']}"
            )

        item = ET.Element("category", attrs)
        item.text = cat.text
        categories.append(item)

    offers = []

    for offer in source_offers:
        oid = (offer.get("id") or "").strip()
        cid = (offer.findtext("categoryId") or "").strip()

        if not oid:
            raise RuntimeError("Товар без offer id")

        if cid not in category_ids:
            raise RuntimeError(
                f"Неверная категория товара {oid}: {cid}"
            )

        price_text = (
            offer.findtext("price") or ""
        ).replace(",", ".").strip()

        try:
            price = float(price_text)
        except ValueError:
            price = 0

        if price < 0.01:
            continue

        offer.find("categoryId").text = f"c{number}_{cid}"
        offers.append(offer)

    if not offers:
        raise RuntimeError("Нет товаров с корректной ценой")

    return {
        "categories": categories,
        "offers": offers,
    }, currencies


def main():
    urls, custom_prices = load_config()
    existing_ids, existing_articles = load_database()
    previous, previous_currencies, baseline = load_previous()

    supplier_data = {}
    statuses = {}
    currency_map = {
        c.get("id"): c
        for c in previous_currencies
        if c.get("id")
    }

    for number, name in SUPPLIERS.items():
        old_count = len(previous[number]["offers"])

        try:
            data, currencies = download_supplier(
                number, urls[number - 1]
            )

            count = len(data["offers"])

            if old_count and count < old_count * MIN_RATIO:
                raise RuntimeError(
                    f"Аномальное сокращение: "
                    f"{old_count} -> {count}"
                )

            supplier_data[number] = data
            statuses[name] = {
                "source": "fresh",
                "offers": count,
            }

            for currency in currencies:
                key = currency.get("id")
                if key and key not in currency_map:
                    currency_map[key] = currency

            print(f"[OK] {name}: {count}", flush=True)

        except Exception as exc:
            old = previous[number]

            if not old["offers"] or not old["categories"]:
                raise RuntimeError(
                    f"{name}: нет пригодной резервной копии"
                ) from exc

            supplier_data[number] = old
            statuses[name] = {
                "source": "previous",
                "offers": len(old["offers"]),
                "reason": str(exc),
            }

            print(
                f"[CACHE] {name}: {len(old['offers'])}; "
                f"причина: {exc}",
                flush=True
            )

    all_offers = []
    seen_ids = set()

    for number, name in SUPPLIERS.items():
        for offer in supplier_data[number]["offers"]:
            oid = (offer.get("id") or "").strip()

            if not oid or oid in seen_ids:
                raise RuntimeError(
                    f"Повторный или пустой offer id: {oid}"
                )

            seen_ids.add(oid)
            all_offers.append((number, offer))

    # Сначала проверяем все существующие товары.
    new_candidates = []
    accepted = []
    exclusions = []
    matched = 0

    for number, offer in all_offers:
        oid = offer.get("id", "").strip()
        code = product_code(offer)
        norm = normalize(code)

        if oid in existing_ids:
            old_code = existing_ids[oid]

            if old_code and old_code != norm:
                raise RuntimeError(
                    f"Существующий ID {oid}: артикул "
                    f"{old_code} не совпадает с {code}"
                )

            accepted.append((number, offer))
            matched += 1

        elif norm and norm in existing_articles:
            exclusions.append((
                number, oid, code,
                "Артикул уже существует в Prom",
                offer.findtext("name") or ""
            ))

        elif not norm:
            exclusions.append((
                number, oid, code,
                "Отсутствует артикул",
                offer.findtext("name") or ""
            ))

        else:
            new_candidates.append((number, offer, norm))

    counts = Counter(
        norm for _, _, norm in new_candidates
    )

    new_count = 0

    for number, offer, norm in new_candidates:
        oid = offer.get("id", "").strip()

        if counts[norm] > 1:
            exclusions.append((
                number, oid, product_code(offer),
                "Повтор артикула среди новых предложений",
                offer.findtext("name") or ""
            ))
        else:
            accepted.append((number, offer))
            new_count += 1

    root = ET.Element(
        "yml_catalog",
        date=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    shop = ET.SubElement(root, "shop")

    ET.SubElement(shop, "name").text = (
        "PlumberShop Suppliers Catalog"
    )
    ET.SubElement(shop, "company").text = "Сантехник"

    currencies = ET.SubElement(shop, "currencies")
    if not currency_map:
        ET.SubElement(
            currencies, "currency", id="UAH", rate="1"
        )
    else:
        for currency in currency_map.values():
            currencies.append(currency)

    categories = ET.SubElement(shop, "categories")
    for number in SUPPLIERS:
        for item in supplier_data[number]["categories"]:
            categories.append(item)

    offers = ET.SubElement(shop, "offers")
    applied_prices = 0

    for number, offer in accepted:
        code = product_code(offer)

        if code in custom_prices:
            price = offer.find("price")
            if price is not None:
                price.text = str(custom_prices[code])
                applied_prices += 1

        offers.append(offer)

    # Публикуемый XML не трогаем: создаём тестовый.
    temp = OUTPUT.with_suffix(".tmp")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(
        temp, encoding="utf-8", xml_declaration=True
    )

    # Проверяем XML перед сохранением результата.
    ET.parse(temp)
    temp.replace(OUTPUT)

    with EXCLUSIONS.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow([
            "supplier", "offer_id", "article",
            "reason", "name"
        ])
        for number, oid, code, reason, name in exclusions:
            writer.writerow([
                SUPPLIERS[number], oid, code, reason, name
            ])

    summary = {
        "baseline": baseline,
        "input_offers": len(all_offers),
        "output_offers": len(accepted),
        "existing_matched": matched,
        "new_candidates": new_count,
        "excluded": len(exclusions),
        "custom_prices_applied": applied_prices,
        "suppliers": statuses,
    }

    REPORT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n=== ИТОГ ===")
    print(json.dumps(
        summary, ensure_ascii=False, indent=2
    ))
    print("Тестовый XML:", OUTPUT)
    print("Исключения:", EXCLUSIONS)


if __name__ == "__main__":
    main()

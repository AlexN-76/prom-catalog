import argparse
import csv
import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

MIXED = {
    "c4_30", "c4_41", "c4_52",
    "c4_60", "c4_88", "c4_89"
}

ACCESSORIES = [
    ("Тримачі для паперу", r"держател\w* (?:для )?(?:туалетн\w* )?бумаг|тримач\w* (?:для )?(?:туалетн\w* )?папер|бумагодержател|паперотримач"),
    ("Йоржики для унітазу", r"\b(?:ерш(?:ик)?|ёрш(?:ик)?|йорж(?:ик)?)\b"),
    ("Сушарки для рук", r"сушилк\w* для рук|сушарк\w* для рук"),
    ("Фени для волосся", r"\bфен\b"),
    ("Дзеркала для ванних кімнат", r"зеркал|дзеркал"),
    ("Мильниці", r"мыльниц|мильниц"),
    ("Диспенсери", r"дозатор|диспенсер"),
    ("Тримачі рушників", r"полотенцедержател|рушникотримач|держател\w* (?:для )?полотен|тримач\w* рушник"),
    ("Полки і етажерки для ванних кімнат", r"\bполк[а-иу]\b|\bполочк|\bполичк|етажерк"),
    ("Підставки і стакани для зубних щіток", r"\bстакан(?:чик)?\b|\bсклянк|щ[еі]тк(?:и|а) для зуб"),
    ("Аксесуари для ванних кімнат", r"\bкрюч(?:ок|ек|ки|кик)|\bгач(?:ок|ки)|\bпоручн|\bвешалк|\bвішалк|планк\w* с крюч|\bнабор\w* аксессуар|\bкомплект\w* аксессуар")
]

MIXER = [
    ("Виливи", r"\bизлив|\bвилив|\bгусак\b|\bгусек\b"),
    ("Запчастини для змішувачів", r"картридж|кран[ -]?букс|дивертор|аэратор|аератор|эксцентрик|ексцентрик|розетк|ремкомплект|ручк|рукоятк|гайк|переключател|перемикач|крепеж|кріплен|декоративн"),
    ("Прокладки гумові", r"прокладк|прокладок"),
    ("Шланги для душу", r"шланг\w* (?:для )?душ"),
    ("Лійки для душу", r"лейк\w* (?:для )?душ|лійк\w* (?:для )?душ")
]

PIPES = [
    ("Втулки під фланець", r"втулк\w* (?:под|під) флан"),
    ("З'єднання «американка»", r"американк"),
    ("Сіделки для труб", r"седелк|сіделк|врезк|врізк"),
    ("Хрестовини", r"крестовин|хрестовин"),
    ("Трійники", r"тройник|трійник|трiйник|трійчак"),
    ("Фільтри грубої очистки", r"\bфильтр\b|\bфільтр\b"),
    ("Косинці для труб", r"уголок|угольник|\bугол\b|кутник|колін\w*"),
    ("Відводи, обходи", r"\bколен[оа]\b|\bотвод|\bвідвод|\bобвод|\bобхід"),
    ("Муфти для труб, монтажні гільзи", r"муфт|муфтов"),
    ("Ніпелі", r"ниппел|ніпел"),
    ("Подовжувачі для труб", r"удлинител|подовжувач"),
    ("Штуцери для труб", r"штуцер|щтуцер"),
    ("Контргайки", r"контргайк"),
    ("Згони", r"\bсгон|\bзгін"),
    ("Заглушки", r"заглушк|заглушок"),
    ("Фланці", r"\bфланец|\bфланець"),
    ("Ревізії для труб", r"\bревизи|\bревіз"),
    ("Хомути, затискачі", r"хомут|затискач"),
    ("Прокладки гумові", r"прокладк|прокладок|ущільнювач"),
    ("Кільця гумові", r"\bкольц\w* резинов|резинов\w* кольц|\bкільц\w* гумов|гумов\w* кільц"),
    ("Клапани", r"\bклапан"),
    ("Сифони, сантехнічні трапи", r"\bсифон"),
    ("Кульові, коркові крани", r"\bкран\w* шаров|шаров\w* кран|\bкран\w* кульов|кульов\w* кран"),
    ("Перехідники", r"переходник|перехідник|футорк|\bпереход\b|\bперехід\b|\bредукци|\bредукцi|\bредукція|адаптер"),
    ("Фітинги для труб, загальне", r"цанг|соединен\w* зажимн|зажимн\w* соединен|\bфитинг\b|\bфітинг\b")
]

PRIMARY = [
    (r"^\s*(?:\d+\s+)?(?:картридж|аэратор|аератор|рукоятк|ручк|кран[ -]?букс|дивертор|гайк|ремкомплект)", "Запчастини для змішувачів"),
    (r"^\s*(?:\d+\s+)?(?:излив|вилив|гусак|гусек)", "Виливи"),
    (r"^\s*(?:\d+\s+)?(?:хрестовин|крестовин)", "Хрестовини"),
    (r"^\s*(?:\d+\s+)?(?:тройник|трійник)", "Трійники"),
    (r"^\s*(?:\d+\s+)?(?:муфт)", "Муфти для труб, монтажні гільзи"),
    (r"^\s*(?:\d+\s+)?(?:ниппел|ніпел)", "Ніпелі"),
    (r"^\s*(?:\d+\s+)?(?:заглушк)", "Заглушки"),
    (r"^\s*(?:\d+\s+)?(?:колен|відвод|отвод)", "Відводи, обходи"),
    (r"^\s*(?:\d+\s+)?(?:угол|кутник)", "Косинці для труб"),
    (r"^\s*(?:\d+\s+)?(?:штуцер|щтуцер)", "Штуцери для труб"),
    (r"^\s*(?:\d+\s+)?(?:кран шаров|кран кульов)", "Кульові, коркові крани"),
    (r"^\s*(?:\d+\s+)?(?:врезк|врізк|сіделк|седелк)", "Сіделки для труб"),
    (r"^\s*(?:\d+\s+)?(?:переходник|перехідник|футорк|редукци)", "Перехідники"),
    (r"^\s*(?:\d+\s+)?(?:прокладк)", "Прокладки гумові")
]

def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def classify(group, title, reference):
    rules = (
        ACCESSORIES if group == "c4_30"
        else MIXER if group == "c4_60"
        else PIPES
    )
    title = " ".join(title.lower().split())
    matches = {
        name for name, pattern in rules
        if name in reference and re.search(pattern, title)
    }
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        for pattern, name in PRIMARY:
            if name in matches and re.search(pattern, title):
                return name
    return None

def run(args):
    reference = {}
    for row in read_csv(args.reference):
        name = row["prom_category_name"].strip()
        cid = row["portal_category_id"].strip()
        if not cid.isdigit():
            raise ValueError(f"Неверный ID категории: {name}")
        if name in reference and reference[name] != cid:
            raise ValueError(f"Конфликт категории: {name}")
        reference[name] = cid

    valid_ids = set(reference.values())
    mapping = {}
    for row in read_csv(args.mapping):
        group = row["supplier_category_id"].strip()
        name = row["prom_category_name"].strip()
        cid = row["portal_category_id"].strip()
        if group in mapping or cid not in valid_ids:
            raise ValueError(f"Неверная группа: {group}")
        if name in reference and reference[name] != cid:
            raise ValueError(f"Конфликт категории: {group}")
        mapping[group] = cid

    overrides = {}
    for row in read_csv(args.overrides):
        oid = row["offer_id"].strip()
        name = row["prom_category_name"].strip()
        if oid in overrides or name not in reference:
            raise ValueError(f"Неверное назначение: {oid}")
        overrides[oid] = (
            row["supplier_group_id"].strip(),
            row["product_code"].strip(),
            reference[name]
        )

    source = Path(args.input)
    output = Path(args.output)
    if source.resolve() == output.resolve():
        raise ValueError("Нельзя перезаписывать исходный XML")

    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rb") as f:
        root = ET.parse(f).getroot()

    shop = root.find("shop")
    categories = shop.find("categories")
    offers = shop.find("offers")

    groups = set()
    stats = Counter()
    review = []
    used_overrides = set()
    seen = set()

    for category in categories.findall("category"):
        group = category.get("id", "")
        if not group or group in groups:
            raise ValueError(f"Некорректная группа: {group}")
        groups.add(group)
        if group in MIXED:
            category.attrib.pop("portal_id", None)
        elif group in mapping:
            category.set("portal_id", mapping[group])

    for item in offers.findall("offer"):
        oid = item.get("id", "")
        group = (item.findtext("categoryId") or "").strip()

        if not oid or oid in seen or group not in groups:
            raise ValueError(f"Некорректный товар: {oid}")

        seen.add(oid)
        stats["total"] += 1
        name = item.findtext("name") or item.findtext("name_ua") or ""
        category_id = None

        if group in MIXED:
            if oid in overrides:
                old_group, old_code, category_id = overrides[oid]
                code = (
                    item.findtext("vendorCode")
                    or item.findtext("article")
                    or ""
                ).strip()
                if (old_group, old_code) != (group, code):
                    raise ValueError(
                        f"Изменился товар с ручным назначением: {oid}"
                    )
                used_overrides.add(oid)
                stats["manual"] += 1
            else:
                choice = classify(group, name, reference)
                if choice:
                    category_id = reference[choice]
                    stats["auto"] += 1
                else:
                    stats["review"] += 1
                    review.append((group, oid, name))

        elif group in mapping:
            category_id = mapping[group]
            stats["group"] += 1
        else:
            stats["unmapped"] += 1
            review.append((group, oid, name))

        if category_id:
            tag = item.find("portal_category_id")
            if tag is None:
                tag = ET.SubElement(item, "portal_category_id")
            tag.text = category_id

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(
        output, encoding="utf-8", xml_declaration=True
    )
    ET.parse(output)

    unused = sorted(set(overrides) - used_overrides)
    report = {
        "counts": dict(stats),
        "unused_overrides": unused
    }

    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with open(args.review, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["supplier_group_id", "offer_id", "name"])
        writer.writerows(review)

    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in (
        "input", "output", "mapping",
        "reference", "overrides", "review", "report"
    ):
        parser.add_argument("--" + arg, required=True)
    run(parser.parse_args())

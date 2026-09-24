#!/usr/bin/env python3
"""Еженедельное обновление вакансий с открытого API «Работы России» (trudvsem.ru).

Раз в неделю GitHub Actions запускает этот скрипт: он ищет свежие вакансии
Ростовской области под каждую академию и переписывает блок vacs в index.html
между маркерами VAC-DATA-START / VAC-DATA-END. Если по запросу ничего свежего
нет — остаются старые записи этой академии (счётчики не падают).
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"
REGION = "61"  # Ростовская область

# (запрос, академия, направление, теги, сколько нужно)
TARGETS = [
    ("юрист", "law", "Юриспруденция", ["юриспруденция"], 3),
    ("психолог", "hum", "Психология", ["психология"], 1),
    ("педагог-психолог", "hum", "Психология", ["психология", "образование"], 1),
    ("специалист по кадрам", "hum", "HR", ["кадры"], 1),
    ("менеджер по продажам", "itd", "Менеджмент", ["продажи"], 1),
    ("инженер-программист", "itd", "IT", ["программирование"], 1),
    ("системный администратор", "itd", "IT", ["сети"], 1),
    ("логист", "itd", "Логистика", ["логистика"], 1),
    ("экономист", "ect", "Экономика", ["экономика"], 2),
    ("аналитик", "ect", "Экономика", ["аналитика"], 3),
    ("бухгалтер", "ect", "Бухучёт", ["бухучёт"], 2),
    ("администратор гостиницы", "ect", "Туризм", ["гостиницы"], 1),
    ("экскурсовод", "ect", "Туризм", ["экскурсии"], 1),
    ("медицинская сестра", "medic", "Медицина", ["сестринское дело"], 2),
    ("стоматолог", "medic", "Медицина", ["стоматология"], 2),
    ("фармацевт", "medic", "Медицина", ["фармация"], 2),
    ("фельдшер", "medic", "Медицина", ["фельдшер"], 1),
    ("зубной техник", "medic", "Медицина", ["зуботехника"], 1),
]

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def api_search(text, limit=12):
    params = {"text": text, "region_code": REGION, "limit": limit}
    url = "https://opendata.trudvsem.ru/api/v1/vacancies?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "iuubip-career-bot", "Accept": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    return data.get("results", {}).get("vacancies", [])


def fmt_num(n):
    return "{:,}".format(n).replace(",", " ")


def fmt_salary(v):
    mn, mx = v.get("salary_min") or 0, v.get("salary_max") or 0
    if mn and mx and mx > mn:
        return "%s–%s ₽" % (fmt_num(mn), fmt_num(mx))
    if mn:
        return "от %s ₽" % fmt_num(mn)
    if mx:
        return "до %s ₽" % fmt_num(mx)
    return "доход не указан"


def fmt_city(v):
    addr = v.get("addresses", {}).get("address", [{}])
    loc = addr[0].get("location", "") if addr else ""
    m = re.search(r"г\.\s*([^,;]+)", loc)
    if m:
        return "г. " + m.group(1).strip()
    return loc.split(",")[0].strip()[:60] or "Ростовская область"


def fmt_date(iso):
    try:
        y, m, d = iso.split("-")[0:3]
        return "%s.%s.%s" % (d, m, y)
    except Exception:
        return iso


def js_str(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def entry(v, acad, direction, tags):
    v = v.get("vacancy", v)
    comp = v.get("company", {}).get("name", "")
    return '{t:"%s",c:"%s",city:"%s",date:"%s",s:"%s",tags:%s,dir:"%s",acad:"%s",u:"%s"}' % (
        js_str(v.get("job-name")), js_str(comp), js_str(fmt_city(v)),
        fmt_date(v.get("creation-date", "")), fmt_salary(v),
        json.dumps(tags, ensure_ascii=False),
        direction, acad, v.get("vac_url", ""))


def old_chunks(block):
    """Старые записи: {url, acad, text, pin}. Помеченные pin:1 не трогаем никогда."""
    out = []
    for m in re.finditer(r"\{t:.*?\}", block, flags=re.S):
        t = m.group(0)
        a = re.search(r'acad:"(\w+)"', t)
        u = re.search(r'u:"([^"]+)"', t)
        if a and u:
            out.append({"url": u.group(1), "acad": a.group(1), "text": t,
                        "pin": "pin:1" in t})
    return out


def main():
    html = PAGE.read_text(encoding="utf-8")
    start = html.index("// VAC-DATA-START")
    end = html.index("// VAC-DATA-END") + len("// VAC-DATA-END")
    old = old_chunks(html[start:end])

    new_entries, used_urls = [], set()
    for o in old:  # закреплённые вручную — всегда сохраняем
        if o["pin"] and o["url"] not in used_urls:
            new_entries.append(o["text"])
            used_urls.add(o["url"])
    print("pinned kept: %d" % len(new_entries))
    for query, acad, direction, tags, need in TARGETS:
        try:
            found = api_search(query)
        except Exception as e:
            print("API error [%s]: %s" % (query, e))
            found = []
        found.sort(key=lambda x: x.get("vacancy", x).get("creation-date", ""), reverse=True)
        got = 0
        for item in found:
            url = item.get("vacancy", item).get("vac_url", "")
            if not url or url in used_urls:
                continue
            new_entries.append(entry(item, acad, direction, tags))
            used_urls.add(url)
            got += 1
            if got >= need:
                break
        if got < need:  # добираем старыми записями той же академии
            for o in old:
                if o["acad"] == acad and o["url"] not in used_urls:
                    new_entries.append(o["text"])
                    used_urls.add(o["url"])
                    got += 1
                    if got >= need:
                        break
        print("%s/%s: +%d fresh" % (acad, query, got))

    today = date.today()
    data_date = "%d %s %d" % (today.day, MONTHS[today.month - 1], today.year)
    data_short = today.strftime("%d.%m.%Y")
    block = ("// VAC-DATA-START\n"
             "const DATA_DATE='%s';const DATA_SHORT='%s';\n"
             "const vacs=[\n%s\n];\n// VAC-DATA-END"
             % (data_date, data_short, ",\n".join(new_entries)))
    new_html = html[:start] + block + html[end:]
    if new_html != html:
        PAGE.write_text(new_html, encoding="utf-8")
        print("index.html updated: %d vacancies, date %s" % (len(new_entries), data_short))
    else:
        print("no changes")


if __name__ == "__main__":
    main()

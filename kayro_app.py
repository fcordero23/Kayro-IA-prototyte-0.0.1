import ui
import os
import re
import ast
import json
import time
import math
import random
import zipfile
import html
import speech
import dialogs
import traceback
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import threading
import queue

try:
    import PyPDF2
except Exception:
    PyPDF2 = None


# =========================================================
# CONFIG
# =========================================================

BRAIN_FILE = "kayro_brain.py"
MORE_CHUNK_SIZE = 18000

USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0; rv:128.0) Gecko/20100101 Firefox/128.0",
]

AUTO_TOPICS = [
    "Puerto Rico", "programación", "matemáticas", "historia", "biología",
    "astronomía", "tecnología", "literatura", "física", "química",
    "inteligencia artificial", "ciberseguridad", "filosofía", "música",
    "arte", "anime", "manga", "videojuegos", "ciencia", "robótica"
]

AUTO_LEARN_THREADS = 4
AUTO_LEARN_PER_CYCLE = 4
AUTO_SLEEP_BETWEEN_REQUESTS = 0.8

SCIENCE_TOPICS = {
    "biología", "astronomía", "física", "química", "ciencia", "robótica",
    "inteligencia artificial", "ciberseguridad", "tecnología", "programación",
    "matemáticas"
}

HUMANITIES_TOPICS = {
    "historia", "literatura", "filosofía", "arte", "música"
}

POP_TOPICS = {
    "anime", "manga", "videojuegos"
}

LANGUAGE_TOPICS = {
    "palabra", "diccionario", "definición", "definicion", "significado"
}

NEWS_TOPICS = {
    "actualidad", "noticias", "Puerto Rico"
}

DEFAULT_BRAIN = {
    "identity": {
        "name": "Kayro IA",
        "mode": "activo",
        "mood": "atento"
    },
    "knowledge": {
        "entries": []
    },
    "stories": {
        "notes": [],
        "story_log": [],
        "novel_mode": {
            "active": False,
            "title": "",
            "scene_index": 0,
            "scene_log": []
        }
    },
    "chat": {
        "history": [],
        "last_topic": "",
        "last_mode": "",
        "last_source": "",
        "last_subject": "",
        "last_full_text": "",
        "last_full_title": "",
        "last_full_mode": "",
        "last_full_index": 0
    },
    "sync": {
        "last_sync": "",
        "seen_general": []
    },
    "cooldowns": {
        "wikipedia": 0,
        "openmeteo": 0,
        "themealdb": 0,
        "google_news": 0
    }
}


# =========================================================
# CARGA / GUARDADO
# =========================================================

def merge_defaults(data, defaults):
    if isinstance(defaults, dict):
        out = {}
        for k, v in defaults.items():
            if k in data:
                out[k] = merge_defaults(data[k], v)
            else:
                out[k] = json.loads(json.dumps(v))
        for k, v in data.items():
            if k not in out:
                out[k] = v
        return out
    return data


def load_brain():
    if os.path.exists(BRAIN_FILE):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("kayro_brain", BRAIN_FILE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            brain = getattr(module, "BRAIN", None)
            if isinstance(brain, dict):
                return merge_defaults(brain, DEFAULT_BRAIN)
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_BRAIN))


BRAIN = load_brain()
BRAIN_LOCK = threading.Lock()


def save_brain():
    with BRAIN_LOCK:
        data_copy = json.loads(json.dumps(BRAIN))

    with open(BRAIN_FILE, "w", encoding="utf-8") as f:
        f.write("# Generado por Kayro IA\n")
        f.write("BRAIN = ")
        f.write(json.dumps(data_copy, ensure_ascii=False, indent=2))


# =========================================================
# UTILIDADES
# =========================================================

def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_ts():
    return int(time.time())


def normalize_spaces(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def split_sentences(text):
    parts = re.split(r"(?<=[\.\!\?])\s+", str(text).strip())
    return [p.strip() for p in parts if p.strip()]


def tokenize(text):
    return re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9_+#\.]{3,}", str(text).lower())


def keyword_tags(text, limit=6):
    stop = {
        "para", "como", "esto", "esta", "porque", "donde", "desde", "sobre",
        "entre", "tiene", "tengo", "quiero", "puede", "puedo", "seria", "estar",
        "hacer", "muy", "más", "mas", "pero", "cuando", "tambien", "solo",
        "algo", "entonces", "mismo", "misma", "cual", "cuál", "este", "ese",
        "esa", "qué", "que", "del", "con", "por", "los", "las", "una", "uno",
        "informacion", "biografia"
    }
    toks = [t for t in tokenize(text) if t not in stop]
    freq = {}
    for t in toks:
        freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in ranked[:limit]]


def similarity_score(query, text):
    q = set(tokenize(query))
    t = set(tokenize(text))
    if not q or not t:
        return 0
    return len(q.intersection(t))


def add_unique(lst, value, max_len=None):
    value = normalize_spaces(value)
    if not value:
        return
    if value not in lst:
        lst.append(value)
    if max_len and len(lst) > max_len:
        del lst[:-max_len]


def choose_nonrepetitive(source_list, seen_list, count):
    with BRAIN_LOCK:
        source_copy = list(source_list)
        random.shuffle(source_copy)
        fresh = [x for x in source_copy if x not in seen_list]

        if len(fresh) < count:
            seen_list[:] = seen_list[-5:]
            fresh = [x for x in source_copy if x not in seen_list]

        chosen = fresh[:count]

        for item in chosen:
            add_unique(seen_list, item, max_len=300)

        return chosen


def safe_filename(name):
    name = normalize_spaces(name).lower()
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name[:80] if name else "kayro_texto"


def speak_text(text):
    try:
        speech.say(text)
    except Exception:
        pass


def natural_prefix(mode="general"):
    if mode == "investigador":
        return random.choice([
            "Bien, fui a buscarlo y esto es lo más útil que encontré.",
            "Te lo organizo mejor para que quede claro.",
            "Mira, esto es lo importante."
        ])
    if mode == "profesor":
        return random.choice([
            "Vamos paso a paso.",
            "Te lo explico claro.",
            "La idea principal es esta."
        ])
    if mode == "programador":
        return random.choice([
            "Perfecto, vamos al punto.",
            "Te lo dejo claro y usable.",
            "Vamos a resolverlo bien."
        ])
    if mode == "escritor":
        return random.choice([
            "Esto se puede poner interesante.",
            "Tengo una buena idea para eso.",
            "Vamos a darle más fuerza."
        ])
    return random.choice([
        "Claro.",
        "Sí, vamos con eso.",
        "Te ayudo.",
        "Entiendo, mira esto."
    ])


# =========================================================
# RED / REQUESTS
# =========================================================

def request_headers(extra=None):
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, text/html, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7"
    }
    if extra:
        headers.update(extra)
    return headers


def source_available(source_name):
    return now_ts() >= int(BRAIN["cooldowns"].get(source_name, 0))


def set_cooldown(source_name, seconds):
    BRAIN["cooldowns"][source_name] = now_ts() + int(seconds)


def fetch_json(url, source_name="wikipedia", timeout=15, extra_headers=None):
    if not source_available(source_name):
        raise RuntimeError(f"{source_name} en cooldown")

    req = urllib.request.Request(url, headers=request_headers(extra_headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code in [429, 403, 503]:
            set_cooldown(source_name, 600)
            save_brain()
        raise


def fetch_text(url, source_name="google_news", timeout=15):
    if not source_available(source_name):
        raise RuntimeError(f"{source_name} en cooldown")

    req = urllib.request.Request(url, headers=request_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code in [429, 403, 503]:
            set_cooldown(source_name, 600)
            save_brain()
        raise


# =========================================================
# MEMORIA
# =========================================================

def add_chat_turn(role, text):
    BRAIN["chat"]["history"].append({
        "role": role,
        "text": normalize_spaces(text),
        "ts": now_str()
    })
    if len(BRAIN["chat"]["history"]) > 250:
        BRAIN["chat"]["history"] = BRAIN["chat"]["history"][-250:]


def update_last_topic(text):
    tags = keyword_tags(text, limit=4)
    if tags:
        BRAIN["chat"]["last_topic"] = ", ".join(tags)
        BRAIN["chat"]["last_subject"] = tags[0]


def set_long_context(title, full_text, mode_name):
    BRAIN["chat"]["last_full_title"] = normalize_spaces(title)
    BRAIN["chat"]["last_full_text"] = full_text or ""
    BRAIN["chat"]["last_full_mode"] = mode_name
    BRAIN["chat"]["last_full_index"] = 0


def get_next_long_chunk():
    text = BRAIN["chat"].get("last_full_text", "") or ""
    idx = int(BRAIN["chat"].get("last_full_index", 0))
    title = BRAIN["chat"].get("last_full_title", "Tema")
    mode_name = BRAIN["chat"].get("last_full_mode", "general")

    if not text:
        return None

    if idx >= len(text):
        return f"i️ Ya te mostré todo lo que tengo guardado sobre {title}."

    end = min(len(text), idx + MORE_CHUNK_SIZE)
    if end < len(text):
        cut = text.rfind(". ", idx, end)
        if cut > idx + 500:
            end = cut + 1

    chunk = text[idx:end].strip()
    BRAIN["chat"]["last_full_index"] = end

    headers = {
        "bio": f"👤 Más biografía sobre {title}\n\n",
        "weather": f"🌦️ Más detalles del pronóstico para {title}\n\n",
        "recipe": f"🍳 Más detalles de la receta: {title}\n\n",
        "programming": f"💻 Más información sobre {title}\n\n",
        "general": f"📚 Más información sobre {title}\n\n",
        "story": f"📖 Continuación sobre {title}\n\n",
        "news": f"📰 Más información sobre {title}\n\n",
        "book": f"📚 Más información sobre {title}\n\n"
    }

    return headers.get(mode_name, f"📚 Más información sobre {title}\n\n") + chunk


def add_memory_entry(topic, summary, category="general", source="local"):
    topic = normalize_spaces(topic)
    summary = str(summary).strip()
    if not topic or not summary:
        return

    with BRAIN_LOCK:
        for item in BRAIN["knowledge"]["entries"]:
            if item["topic"].lower() == topic.lower() and item["summary"] == summary:
                return

        BRAIN["knowledge"]["entries"].append({
            "topic": topic,
            "summary": summary,
            "category": category,
            "source": source,
            "ts": now_str()
        })

        if len(BRAIN["knowledge"]["entries"]) > 2500:
            BRAIN["knowledge"]["entries"] = BRAIN["knowledge"]["entries"][-2500:]


def search_local_knowledge(query, category=None, limit=4):
    scored = []
    for item in BRAIN["knowledge"]["entries"]:
        if category and item["category"] != category:
            continue
        hay = f"{item['topic']} {item['summary']}"
        score = similarity_score(query, hay)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def export_last_text_to_txt():
    title = BRAIN["chat"].get("last_full_title", "") or "kayro_texto"
    full_text = BRAIN["chat"].get("last_full_text", "") or ""

    if not full_text.strip():
        return None, "No hay información guardada para exportar todavía."

    filename = safe_filename(title) + ".txt"
    filepath = os.path.join(os.path.expanduser("~/Documents"), filename)

    content = f"{title}\n"
    content += "=" * len(title) + "\n\n"
    content += full_text

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath, f"✅ Archivo guardado correctamente:\n{filepath}"
    except Exception as e:
        return None, f"No pude guardar el archivo.\nError: {e}"


# =========================================================
# WIKIPEDIA
# =========================================================

def wikipedia_search_title_es(topic):
    params = {
        "action": "query",
        "list": "search",
        "srsearch": topic,
        "utf8": 1,
        "format": "json",
        "srlimit": 1
    }
    url = "https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    data = fetch_json(url, source_name="wikipedia")
    search = data.get("query", {}).get("search", [])
    if search:
        return search[0].get("title", topic)
    return topic


def wikipedia_summary_es(topic):
    exact_title = wikipedia_search_title_es(topic)
    title = urllib.parse.quote(exact_title.replace(" ", "_"))
    url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{title}"
    data = fetch_json(url, source_name="wikipedia")
    return {
        "title": data.get("title", exact_title),
        "summary": normalize_spaces(data.get("extract", "")),
        "source": "Wikipedia ES"
    }


def wikipedia_full_plaintext_es(topic):
    exact_title = wikipedia_search_title_es(topic)

    url = "https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "parse",
        "page": exact_title,
        "prop": "text",
        "format": "json",
        "formatversion": 2
    })

    data = fetch_json(url, source_name="wikipedia")
    html_text = data.get("parse", {}).get("text", "")

    if not html_text:
        return wikipedia_summary_es(topic)

    html_text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    html_text = re.sub(r"(?is)<style.*?>.*?</style>", " ", html_text)
    html_text = re.sub(r"(?is)<table.*?>.*?</table>", " ", html_text)
    html_text = re.sub(r"(?is)<sup.*?>.*?</sup>", " ", html_text)

    html_text = re.sub(r"(?i)<br\s*/?>", "\n", html_text)
    html_text = re.sub(r"(?i)</p>", "\n\n", html_text)
    html_text = re.sub(r"(?i)</div>", "\n", html_text)
    html_text = re.sub(r"(?i)</li>", "\n", html_text)
    html_text = re.sub(r"(?i)</h[1-6]>", "\n\n", html_text)

    text = re.sub(r"(?s)<.*?>", " ", html_text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return {
        "title": normalize_spaces(data.get("parse", {}).get("title", exact_title)),
        "summary": text,
        "source": "Wikipedia FULL"
    }


# =========================================================
# DICCIONARIO / BIBLIOTECA / NOTICIAS
# =========================================================

def wiktionary_lookup_es(word):
    query = normalize_spaces(word)
    search_url = "https://es.wiktionary.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "utf8": 1,
        "format": "json",
        "srlimit": 1
    })

    data = fetch_json(search_url, source_name="wikipedia")
    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    title = results[0].get("title", query)
    return {
        "title": title,
        "summary": f"Encontré la palabra o término '{title}' en Wiktionary.",
        "source": "Wiktionary ES"
    }


def openlibrary_search(query, limit=5):
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode({
        "q": query,
        "limit": limit,
        "language": "spa"
    })
    data = fetch_json(url, source_name="wikipedia")
    docs = data.get("docs", [])
    results = []

    for d in docs[:limit]:
        title = normalize_spaces(d.get("title", ""))
        author = ", ".join(d.get("author_name", [])[:2]) if d.get("author_name") else "Autor desconocido"
        year = d.get("first_publish_year", "")
        subjects = ", ".join(d.get("subject", [])[:8]) if d.get("subject") else ""
        if title:
            results.append({
                "title": title,
                "author": author,
                "year": year,
                "subjects": subjects
            })
    return results


def google_news_rss(query, limit=5):
    rss_url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query + " when:7d",
        "hl": "es-419",
        "gl": "US",
        "ceid": "US:es-419"
    })

    xml_text = fetch_text(rss_url, source_name="google_news")
    root = ET.fromstring(xml_text)
    items = []
    channel = root.find("channel")
    if channel is None:
        return items

    for item in channel.findall("item")[:limit]:
        title = normalize_spaces(item.findtext("title", ""))
        link = normalize_spaces(item.findtext("link", ""))
        pub = normalize_spaces(item.findtext("pubDate", ""))
        if title:
            items.append({
                "title": title,
                "link": link,
                "pubDate": pub
            })
    return items


# =========================================================
# RECETAS
# =========================================================

def parse_recipe_meal(meal):
    title = normalize_spaces(meal.get("strMeal", "Receta"))
    category = normalize_spaces(meal.get("strCategory", ""))
    area = normalize_spaces(meal.get("strArea", ""))
    instructions = normalize_spaces(meal.get("strInstructions", ""))

    ingredients = []
    for i in range(1, 21):
        ing = normalize_spaces(meal.get(f"strIngredient{i}", ""))
        meas = normalize_spaces(meal.get(f"strMeasure{i}", ""))
        if ing and ing.lower() not in ["", "null"]:
            ingredients.append(f"- {ing}: {meas}".strip())

    full = (
        f"Receta: {title}\n"
        f"Categoría: {category}\n"
        f"Origen: {area}\n\n"
        f"Ingredientes:\n" + ("\n".join(ingredients) if ingredients else "No disponibles") +
        f"\n\nPreparación:\n{instructions}"
    )

    return {
        "title": title,
        "summary": f"Categoría: {category}. Origen: {area}.",
        "full": full
    }


def search_recipe(query):
    if not source_available("themealdb"):
        raise RuntimeError("themealdb en cooldown")

    url = "https://www.themealdb.com/api/json/v1/1/search.php?" + urllib.parse.urlencode({
        "s": query
    })
    data = fetch_json(url, source_name="themealdb")
    meals = data.get("meals", None)
    if not meals:
        return None
    return parse_recipe_meal(meals[0])


# =========================================================
# CLIMA
# =========================================================

WEATHER_CODE_MAP = {
    0: "cielo despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna ligera",
    53: "llovizna moderada",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia moderada",
    65: "lluvia intensa",
    71: "nieve ligera",
    73: "nieve moderada",
    75: "nieve intensa",
    80: "chubascos ligeros",
    81: "chubascos moderados",
    82: "chubascos intensos",
    95: "tormenta"
}


def extract_location_from_weather_query(text):
    t = normalize_spaces(text)
    low = t.lower()
    patterns = [
        "clima en ",
        "tiempo en ",
        "pronóstico en ",
        "pronostico en ",
        "temperatura en "
    ]
    for p in patterns:
        idx = low.find(p)
        if idx != -1:
            return normalize_spaces(t[idx + len(p):])
    return t


def geocode_location(location_name):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({
        "name": location_name,
        "count": 1,
        "language": "es",
        "format": "json"
    })
    data = fetch_json(url, source_name="openmeteo")
    results = data.get("results", [])
    if not results:
        return None

    r = results[0]
    return {
        "name": normalize_spaces(r.get("name", location_name)),
        "country": normalize_spaces(r.get("country", "")),
        "admin1": normalize_spaces(r.get("admin1", "")),
        "latitude": r.get("latitude"),
        "longitude": r.get("longitude")
    }


def weather_forecast(location_name):
    place = geocode_location(location_name)
    if not place:
        return None

    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "current": "temperature_2m,relative_humidity_2m,weathercode,wind_speed_10m",
        "timezone": "auto",
        "forecast_days": 3,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch"
    })

    data = fetch_json(url, source_name="openmeteo")
    current = data.get("current", {})
    daily = data.get("daily", {})

    full_lines = []
    current_desc = WEATHER_CODE_MAP.get(current.get("weathercode", -1), "condición no especificada")
    full_lines.append(
        f"Ubicación: {place['name']}, {place['admin1']}, {place['country']}\n"
        f"Ahora mismo: {current.get('temperature_2m', 'N/D')}°F, {current_desc}, "
        f"humedad {current.get('relative_humidity_2m', 'N/D')}%, "
        f"viento {current.get('wind_speed_10m', 'N/D')} mph."
    )

    dates = daily.get("time", [])
    maxs = daily.get("temperature_2m_max", [])
    mins = daily.get("temperature_2m_min", [])
    probs = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    for i in range(min(3, len(dates))):
        desc = WEATHER_CODE_MAP.get(codes[i], "condición variable")
        full_lines.append(
            f"{dates[i]}: {desc}. Máxima {maxs[i]}°F, mínima {mins[i]}°F, "
            f"probabilidad de precipitación {probs[i]}%."
        )

    full_text = "\n\n".join(full_lines)
    short = full_lines[0] + "\n\n" + "\n".join(full_lines[1:])

    return {
        "title": place["name"],
        "summary": short,
        "full": full_text
    }


# =========================================================
# ARCHIVOS
# =========================================================

def read_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def read_pdf(path):
    if PyPDF2 is None:
        return ""
    parts = []
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                if txt:
                    parts.append(txt)
    except Exception:
        return ""
    return "\n".join(parts)


def read_epub(path):
    parts = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                low = name.lower()
                if low.endswith(".xhtml") or low.endswith(".html") or low.endswith(".htm"):
                    try:
                        data = z.read(name)
                        root = ET.fromstring(data)
                        for elem in root.iter():
                            if elem.text:
                                parts.append(elem.text)
                    except Exception:
                        pass
    except Exception:
        return ""
    return "\n".join(parts)


def read_zip(path):
    collected = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                low = name.lower()
                if low.endswith(".txt"):
                    collected.append(z.read(name).decode("utf-8", "ignore"))
                elif low.endswith(".epub"):
                    tmp = "/tmp/_kayro_tmp.epub"
                    try:
                        with open(tmp, "wb") as f:
                            f.write(z.read(name))
                        collected.append(read_epub(tmp))
                    except Exception:
                        pass
                elif low.endswith(".pdf"):
                    tmp = "/tmp/_kayro_tmp.pdf"
                    try:
                        with open(tmp, "wb") as f:
                            f.write(z.read(name))
                        collected.append(read_pdf(tmp))
                    except Exception:
                        pass
    except Exception:
        return ""
    return "\n".join(collected)


def learn_file(path):
    low = path.lower()
    content = ""

    if low.endswith(".txt"):
        content = read_txt(path)
    elif low.endswith(".pdf"):
        content = read_pdf(path)
    elif low.endswith(".epub"):
        content = read_epub(path)
    elif low.endswith(".zip"):
        content = read_zip(path)
    else:
        return "Formato no soportado."

    if not content.strip():
        return "No pude leer contenido útil del archivo."

    for s in split_sentences(content)[:60]:
        if len(s) > 70:
            add_memory_entry("Conocimiento aprendido de archivo", s, category="general", source="archivo")
            add_unique(BRAIN["stories"]["notes"], s, max_len=2500)

    save_brain()
    return "🧠 Archivo aprendido correctamente."


# =========================================================
# DETECTORES
# =========================================================

def looks_like_math(text):
    low = text.lower()
    if any(k in low for k in ["cuánto es", "cuanto es", "resuelve", "calcula", "% de", "sqrt", "raiz", "raíz"]):
        return True
    return bool(re.fullmatch(r"[\d\.\+\-\*\/\(\)\^\s%]+", text.strip()))


def looks_like_programming_request(text):
    t = text.lower()
    keys = [
        "código", "codigo", "programa", "script", "función", "funcion",
        "python", "javascript", "html", "css", "java", "c++", "sql", "bash",
        "api", "algoritmo", "bug", "error", "corrige", "arregla"
    ]
    return any(k in t for k in keys)


def looks_like_bio_request(text):
    t = text.lower()
    return any(k in t for k in ["biografía", "biografia", "quién es", "quien es", "vida de"])


def looks_like_recipe_request(text):
    t = text.lower()
    return any(k in t for k in ["receta", "recetas", "ingredientes", "preparación", "preparacion", "cocinar"])


def looks_like_weather_request(text):
    t = text.lower()
    return any(k in t for k in ["clima", "tiempo", "pronóstico", "pronostico", "temperatura", "lloverá", "llovera"])


def looks_like_news_request(text):
    t = text.lower()
    return any(k in t for k in ["noticia", "noticias", "actualidad", "últimas", "ultimas"])


def looks_like_dictionary_request(text):
    t = text.lower()
    return any(k in t for k in ["define", "definición", "definicion", "significado", "diccionario", "palabra"])


def looks_like_library_request(text):
    t = text.lower()
    return any(k in t for k in ["biblioteca", "libro", "libros", "autor"])


def wants_more_info(text):
    t = text.lower()
    return any(p in t for p in [
        "más información", "mas informacion", "más detalles", "mas detalles",
        "amplía", "amplia", "quiero más", "quiero mas", "más completo", "mas completo"
    ])


def detect_expert_mode(text):
    t = text.lower()
    if looks_like_programming_request(t):
        return "programador"
    if looks_like_math(t):
        return "profesor"
    if any(x in t for x in ["historia", "cuento", "novela", "trama", "personaje"]):
        return "escritor"
    if any(x in t for x in ["investiga", "biografía", "biografia", "noticia", "documental", "clima"]):
        return "investigador"
    if any(x in t for x in ["explica", "enseña", "estudia"]):
        return "profesor"
    return "general"


# =========================================================
# RESPUESTAS
# =========================================================

def solve_math(user_text):
    original = user_text.strip()
    low = original.lower()

    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*de\s*(\d+(?:\.\d+)?)", low)
    if m:
        p = float(m.group(1))
        n = float(m.group(2))
        result = (p / 100.0) * n
        set_long_context(original, f"Resultado de la operación: {result}", "math")
        BRAIN["chat"]["last_mode"] = "math"
        return f"🧮 Resultado\n\nEl {p}% de {n} es {result}."

    expr = re.sub(r"(?i)^cu[aá]nto es\s*", "", original)
    expr = re.sub(r"(?i)^resuelve\s*", "", expr)
    expr = re.sub(r"(?i)^calcula\s*", "", expr)
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/").replace("%", "/100")
    expr = expr.replace("raíz", "sqrt").replace("raiz", "sqrt").replace("√", "sqrt")

    allowed_funcs = {"sqrt": math.sqrt, "abs": abs, "round": round}
    allowed_consts = {"pi": math.pi, "e": math.e}

    def safe_eval(node):
        if isinstance(node, ast.Expression):
            return safe_eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Constante no permitida")
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.BinOp):
            left = safe_eval(node.left)
            right = safe_eval(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.Pow): return left ** right
            if isinstance(node.op, ast.Mod): return left % right
            raise ValueError("Operación no permitida")
        if isinstance(node, ast.UnaryOp):
            val = safe_eval(node.operand)
            if isinstance(node.op, ast.UAdd): return +val
            if isinstance(node.op, ast.USub): return -val
            raise ValueError("Operación no permitida")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in allowed_funcs:
                args = [safe_eval(a) for a in node.args]
                return allowed_funcs[node.func.id](*args)
            raise ValueError("Función no permitida")
        if isinstance(node, ast.Name):
            if node.id in allowed_consts:
                return allowed_consts[node.id]
            raise ValueError("Nombre no permitido")
        raise ValueError("Expresión no permitida")

    try:
        tree = ast.parse(expr, mode="eval")
        result = safe_eval(tree)
        set_long_context(original, f"Resultado de la operación: {result}", "math")
        BRAIN["chat"]["last_mode"] = "math"
        return f"🧮 Resultado\n\n{original}\n\n= {result}"
    except Exception:
        return "No pude resolver esa operación todavía. Prueba con algo como: 25*8, sqrt(81), 15% de 200, o (5+3)^2."


def infer_language(text):
    t = text.lower()
    if "python" in t: return "python"
    if "javascript" in t or " js " in f" {t} ": return "javascript"
    if "html" in t: return "html"
    if "css" in t: return "css"
    if "java" in t and "javascript" not in t: return "java"
    if "c++" in t or "cpp" in t: return "c++"
    if "sql" in t: return "sql"
    if "bash" in t or "shell" in t or "terminal" in t: return "bash"
    return "python"


def generate_code_template(prompt):
    lang = infer_language(prompt)
    if lang == "python":
        return """```python
def main():
    print("Hola desde Kayro IA")

if __name__ == "__main__":
    main()
```"""
    if lang == "javascript":
        return """```javascript
function saludar(nombre) {
  return `Hola, ${nombre}`;
}

console.log(saludar("Kayro"));
```"""
    if lang == "html":
        return """```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Kayro IA</title>
</head>
<body>
  <h1>Hola desde Kayro IA</h1>
</body>
</html>
```"""
    return "```text\nPlantilla básica no disponible todavía.\n```"


def explain_programming_topic(query, extra_long=False):
    local = search_local_knowledge(query, category="programming", limit=3)
    if local and not extra_long:
        best = local[0]
        BRAIN["chat"]["last_mode"] = "programming"
        BRAIN["chat"]["last_source"] = "memoria"
        BRAIN["chat"]["last_subject"] = best["topic"]
        set_long_context(best["topic"], best["summary"], "programming")
        return f"💻 Programación\n\nTema: {best['topic']}\n\n{best['summary']}"

    online = wikipedia_full_plaintext_es(query)
    if online and online["summary"]:
        add_memory_entry(online["title"], online["summary"], category="programming", source=online["source"])
        save_brain()
        BRAIN["chat"]["last_mode"] = "programming"
        BRAIN["chat"]["last_source"] = online["source"]
        BRAIN["chat"]["last_subject"] = online["title"]
        set_long_context(online["title"], online["summary"], "programming")
        return get_next_long_chunk()

    return "No tengo suficiente conocimiento de programación sobre eso todavía."


def generate_code_answer(query, extra_long=False):
    lang = infer_language(query)
    concept = explain_programming_topic(query, extra_long=extra_long)
    code = generate_code_template(query)
    return f"""💻 Respuesta de programación

Lenguaje detectado: {lang}

{concept}

Código base:
{code}"""


def answer_bio_query(query, extra_long=False):
    local = search_local_knowledge(query, category="bio", limit=3)
    if local and not extra_long:
        best = local[0]
        BRAIN["chat"]["last_mode"] = "bio"
        BRAIN["chat"]["last_source"] = "memoria"
        BRAIN["chat"]["last_subject"] = best["topic"]
        set_long_context(best["topic"], best["summary"], "bio")
        return f"👤 Biografía encontrada\n\n{best['topic']}\n\n{best['summary']}"

    online = wikipedia_full_plaintext_es(query)
    if online and online["summary"]:
        add_memory_entry(online["title"], online["summary"], category="bio", source=online["source"])
        save_brain()
        BRAIN["chat"]["last_mode"] = "bio"
        BRAIN["chat"]["last_source"] = online["source"]
        BRAIN["chat"]["last_subject"] = online["title"]
        set_long_context(online["title"], online["summary"], "bio")
        return get_next_long_chunk()

    return "No pude encontrar una biografía clara ahora mismo."


def answer_general_query(query, extra_long=False):
    local = []
    for cat in ["general", "science", "humanities", "pop_culture", "news", "book", "dictionary"]:
        local.extend(search_local_knowledge(query, category=cat, limit=2))

    local = sorted(
        local,
        key=lambda item: similarity_score(query, f"{item['topic']} {item['summary']}"),
        reverse=True
    )

    if local and not extra_long:
        best = local[0]
        BRAIN["chat"]["last_mode"] = "general"
        BRAIN["chat"]["last_source"] = "memoria"
        BRAIN["chat"]["last_subject"] = best["topic"]
        set_long_context(best["topic"], best["summary"], "general")
        return f"📘 Información encontrada\n\nTema: {best['topic']}\n\n{best['summary']}"

    online = wikipedia_full_plaintext_es(query)
    if online and online["summary"]:
        add_memory_entry(online["title"], online["summary"], category="general", source=online["source"])
        save_brain()
        BRAIN["chat"]["last_mode"] = "general"
        BRAIN["chat"]["last_source"] = online["source"]
        BRAIN["chat"]["last_subject"] = online["title"]
        set_long_context(online["title"], online["summary"], "general")
        return get_next_long_chunk()

    return "No pude encontrar información útil ahora mismo."


def answer_dictionary_query(query):
    result = wiktionary_lookup_es(query)
    if result:
        add_memory_entry(result["title"], result["summary"], category="dictionary", source=result["source"])
        save_brain()
        BRAIN["chat"]["last_mode"] = "dictionary"
        BRAIN["chat"]["last_source"] = result["source"]
        BRAIN["chat"]["last_subject"] = result["title"]
        set_long_context(result["title"], result["summary"], "general")
        return f"📖 Diccionario\n\nPalabra/Tema: {result['title']}\n\n{result['summary']}"
    return "No encontré esa palabra en diccionario ahora mismo."


def answer_library_query(query):
    results = openlibrary_search(query, limit=5)
    if results:
        lines = []
        full_parts = []
        for r in results:
            summary = f"Autor: {r['author']}. Año: {r['year']}. Temas: {r['subjects']}"
            add_memory_entry(r["title"], summary, category="book", source="Open Library")
            lines.append(f"- {r['title']}\n  {summary}")
            full_parts.append(f"{r['title']}. {summary}")
        save_brain()
        BRAIN["chat"]["last_mode"] = "book"
        BRAIN["chat"]["last_source"] = "Open Library"
        BRAIN["chat"]["last_subject"] = query
        set_long_context(f"Biblioteca sobre {query}", "\n\n".join(full_parts), "book")
        return "📚 Resultados de biblioteca:\n\n" + "\n".join(lines)
    return "No encontré resultados útiles en biblioteca ahora mismo."


def answer_news_query(query):
    results = google_news_rss(query, limit=5)
    if results:
        lines = []
        full_parts = []
        for r in results:
            summary = f"Publicado: {r['pubDate']}. Enlace: {r['link']}"
            add_memory_entry(r["title"], summary, category="news", source="Google News RSS")
            lines.append(f"- {r['title']}\n  {summary}")
            full_parts.append(f"{r['title']}. {summary}")
        save_brain()
        BRAIN["chat"]["last_mode"] = "news"
        BRAIN["chat"]["last_source"] = "Google News RSS"
        BRAIN["chat"]["last_subject"] = query
        set_long_context(f"Noticias sobre {query}", "\n\n".join(full_parts), "news")
        return "📰 Noticias encontradas:\n\n" + "\n".join(lines)
    return "No pude encontrar noticias ahora mismo."


def answer_recipe_query(query):
    recipe_query = query.lower().replace("receta de", "").replace("dame receta de", "").strip()
    result = search_recipe(recipe_query or query)
    if result:
        add_memory_entry(result["title"], result["summary"], category="recipe", source="TheMealDB")
        save_brain()
        BRAIN["chat"]["last_mode"] = "recipe"
        BRAIN["chat"]["last_source"] = "TheMealDB"
        BRAIN["chat"]["last_subject"] = result["title"]
        set_long_context(result["title"], result["full"], "recipe")
        return get_next_long_chunk()
    return "No pude encontrar una receta clara ahora mismo."


def answer_weather_query(query):
    location = extract_location_from_weather_query(query)
    result = weather_forecast(location)
    if result:
        add_memory_entry(result["title"], result["summary"], category="weather", source="Open-Meteo")
        save_brain()
        BRAIN["chat"]["last_mode"] = "weather"
        BRAIN["chat"]["last_source"] = "Open-Meteo"
        BRAIN["chat"]["last_subject"] = result["title"]
        set_long_context(result["title"], result["full"], "weather")
        return f"🌦️ Pronóstico para {result['title']}\n\n{result['summary']}"
    return "No pude obtener el pronóstico para esa ubicación ahora mismo."


def generate_story(prompt=""):
    note = random.choice(BRAIN["stories"]["notes"]) if BRAIN["stories"]["notes"] else "El ambiente se vuelve extraño y lleno de posibilidades."
    text = f"""📖 Historia de Kayro

Todo comienza cuando algo cambia de forma inesperada.

{note}

El protagonista avanza entre dudas, señales ocultas y una amenaza que todavía no entiende por completo. Cada paso revela algo nuevo y la atmósfera se vuelve más intensa.
"""
    add_unique(BRAIN["stories"]["story_log"], text, max_len=500)
    BRAIN["chat"]["last_mode"] = "story"
    BRAIN["chat"]["last_source"] = "story_engine"
    BRAIN["chat"]["last_subject"] = "historia"
    set_long_context("Historia actual", text, "story")
    return text


def generate_story_continuation():
    prev = BRAIN["stories"]["story_log"][-1] if BRAIN["stories"]["story_log"] else ""
    text = f"""📖 Continuación

La historia sigue creciendo.

{prev[:320]}

Ahora aparecen nuevas pistas, nuevas tensiones y una decisión difícil que cambiará el rumbo de todo.
"""
    add_unique(BRAIN["stories"]["story_log"], text, max_len=500)
    BRAIN["chat"]["last_mode"] = "story"
    BRAIN["chat"]["last_source"] = "story_engine"
    BRAIN["chat"]["last_subject"] = "historia"
    set_long_context("Historia actual", text, "story")
    return text


def start_novel_mode(theme=""):
    novel = BRAIN["stories"]["novel_mode"]
    novel["active"] = True
    novel["title"] = "Novela de Kayro" if not theme else "Novela de Kayro: " + normalize_spaces(theme).title()
    novel["scene_index"] = 0
    novel["scene_log"] = []
    BRAIN["chat"]["last_mode"] = "story"
    BRAIN["chat"]["last_source"] = "story_engine"
    BRAIN["chat"]["last_subject"] = novel["title"]
    set_long_context(novel["title"], novel["title"], "story")
    return f"📚 Modo novela activado\n\nTítulo: {novel['title']}"


def continue_novel_scene():
    novel = BRAIN["stories"]["novel_mode"]
    if not novel["active"]:
        return "No hay una novela activa."

    novel["scene_index"] += 1
    scene = f"""🎬 Escena {novel['scene_index']}

La tensión sube. El mundo responde de forma inesperada y el protagonista entiende que ya no hay marcha atrás.
"""
    novel["scene_log"].append(scene)
    set_long_context(novel["title"], "\n\n".join(novel["scene_log"]), "story")
    return scene


def continue_previous_mode(user_text):
    low = user_text.lower().strip()
    if low in [
        "más información", "mas informacion", "más", "mas", "amplía", "amplia",
        "continúa", "continua", "explícalo", "explicalo"
    ]:
        more = get_next_long_chunk()
        if more:
            return more

        if BRAIN["chat"].get("last_mode") == "story":
            return generate_story_continuation()

    return None


def interpret_input(user_text):
    user_text = normalize_spaces(user_text)
    update_last_topic(user_text)

    continued = continue_previous_mode(user_text)
    if continued:
        return continued

    prefix = natural_prefix(detect_expert_mode(user_text))
    low = user_text.lower()

    if looks_like_math(user_text):
        return prefix + "\n\n" + solve_math(user_text)

    if looks_like_weather_request(user_text):
        return prefix + "\n\n" + answer_weather_query(user_text)

    if looks_like_recipe_request(user_text):
        return prefix + "\n\n" + answer_recipe_query(user_text)

    if looks_like_bio_request(user_text):
        return prefix + "\n\n" + answer_bio_query(user_text, extra_long=wants_more_info(user_text))

    if looks_like_news_request(user_text):
        return prefix + "\n\n" + answer_news_query(user_text)

    if looks_like_dictionary_request(user_text):
        return prefix + "\n\n" + answer_dictionary_query(user_text)

    if looks_like_library_request(user_text):
        return prefix + "\n\n" + answer_library_query(user_text)

    if looks_like_programming_request(user_text):
        return prefix + "\n\n" + generate_code_answer(user_text, extra_long=wants_more_info(user_text))

    if any(x in low for x in ["historia", "cuento", "trama"]):
        return prefix + "\n\n" + generate_story(user_text)

    if any(x in low for x in ["inicia novela", "modo novela", "novela larga"]):
        return prefix + "\n\n" + start_novel_mode(user_text)

    if any(x in low for x in ["siguiente escena", "continua novela", "continúa novela"]):
        return prefix + "\n\n" + continue_novel_scene()

    return prefix + "\n\n" + answer_general_query(user_text, extra_long=wants_more_info(user_text))


# =========================================================
# AUTOAPRENDIZAJE PARALELO
# =========================================================

def detect_topic_profile(topic):
    t = normalize_spaces(topic).lower()

    profile = {
        "use_wikipedia": True,
        "use_books": True,
        "use_news": True,
        "use_dictionary": False,
        "book_limit": 2,
        "news_limit": 2
    }

    if t in SCIENCE_TOPICS:
        profile["use_wikipedia"] = True
        profile["use_books"] = True
        profile["use_news"] = True
        profile["use_dictionary"] = False
        profile["book_limit"] = 2
        profile["news_limit"] = 3
        return profile

    if t in HUMANITIES_TOPICS:
        profile["use_wikipedia"] = True
        profile["use_books"] = True
        profile["use_news"] = False
        profile["use_dictionary"] = False
        profile["book_limit"] = 3
        profile["news_limit"] = 1
        return profile

    if t in POP_TOPICS:
        profile["use_wikipedia"] = True
        profile["use_books"] = True
        profile["use_news"] = True
        profile["use_dictionary"] = False
        profile["book_limit"] = 2
        profile["news_limit"] = 2
        return profile

    if t in NEWS_TOPICS:
        profile["use_wikipedia"] = True
        profile["use_books"] = False
        profile["use_news"] = True
        profile["use_dictionary"] = False
        profile["book_limit"] = 1
        profile["news_limit"] = 4
        return profile

    if t in LANGUAGE_TOPICS or "palabra" in t or "significado" in t:
        profile["use_wikipedia"] = False
        profile["use_books"] = False
        profile["use_news"] = False
        profile["use_dictionary"] = True
        profile["book_limit"] = 0
        profile["news_limit"] = 0
        return profile

    return profile


def classify_memory_category(topic):
    t = normalize_spaces(topic).lower()

    if t in SCIENCE_TOPICS:
        return "science"
    if t in HUMANITIES_TOPICS:
        return "humanities"
    if t in POP_TOPICS:
        return "pop_culture"
    if t in NEWS_TOPICS:
        return "news"
    if t in LANGUAGE_TOPICS:
        return "dictionary"
    return "general"


def learn_topic_from_sources(topic):
    learned = []
    profile = detect_topic_profile(topic)
    memory_category = classify_memory_category(topic)

    if profile["use_wikipedia"]:
        try:
            result = wikipedia_summary_es(topic)
            if result and result["summary"]:
                add_memory_entry(
                    result["title"],
                    result["summary"],
                    category=memory_category,
                    source=result["source"]
                )
                learned.append(f"🌐 Wikipedia: {result['title']}")
        except Exception as e:
            learned.append(f"⚠️ Wikipedia fallo con {topic}: {e}")

        time.sleep(AUTO_SLEEP_BETWEEN_REQUESTS)

    if profile["use_books"]:
        try:
            books = openlibrary_search(topic, limit=profile["book_limit"])
            for b in books:
                summary = f"Autor: {b['author']}. Año: {b['year']}. Temas: {b['subjects']}"
                add_memory_entry(
                    b["title"],
                    summary,
                    category="book",
                    source="Open Library"
                )
                learned.append(f"📚 Libro: {b['title']}")
        except Exception as e:
            learned.append(f"⚠️ Biblioteca fallo con {topic}: {e}")

        time.sleep(AUTO_SLEEP_BETWEEN_REQUESTS)

    if profile["use_news"]:
        try:
            news = google_news_rss(topic, limit=profile["news_limit"])
            for n in news:
                summary = f"Publicado: {n['pubDate']}. Enlace: {n['link']}"
                add_memory_entry(
                    n["title"],
                    summary,
                    category="news",
                    source="Google News RSS"
                )
                learned.append(f"📰 Noticia: {n['title']}")
        except Exception as e:
            learned.append(f"⚠️ Noticias fallo con {topic}: {e}")

        time.sleep(AUTO_SLEEP_BETWEEN_REQUESTS)

    if profile["use_dictionary"]:
        try:
            dic = wiktionary_lookup_es(topic)
            if dic:
                add_memory_entry(
                    dic["title"],
                    dic["summary"],
                    category="dictionary",
                    source=dic["source"]
                )
                learned.append(f"📖 Diccionario: {dic['title']}")
        except Exception as e:
            learned.append(f"⚠️ Diccionario fallo con {topic}: {e}")

    return learned


def auto_learn_worker(topic, results_queue):
    try:
        learned = learn_topic_from_sources(topic)
        results_queue.put({
            "topic": topic,
            "ok": True,
            "items": learned
        })
    except Exception as e:
        results_queue.put({
            "topic": topic,
            "ok": False,
            "items": [f"❌ Error general con {topic}: {e}"]
        })


def auto_learn_batch_parallel():
    topics = choose_nonrepetitive(
        AUTO_TOPICS,
        BRAIN["sync"]["seen_general"],
        AUTO_LEARN_PER_CYCLE
    )

    results_queue = queue.Queue()
    threads = []

    for topic in topics[:AUTO_LEARN_THREADS]:
        t = threading.Thread(
            target=auto_learn_worker,
            args=(topic, results_queue),
            daemon=True
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    learned = []
    while not results_queue.empty():
        result = results_queue.get()
        learned.extend(result["items"])

    with BRAIN_LOCK:
        BRAIN["sync"]["last_sync"] = now_str()

    save_brain()
    return learned


# =========================================================
# UI
# =========================================================

class KayroApp(ui.View):
    def __init__(self):
        self.name = "Kayro IA 🧠"
        self.background_color = "#0f172a"

        self.auto_running = False
        self.auto_session_learned = []
        self.auto_cycle_count = 0

        self.output = ui.TextView()
        self.output.background_color = "#0f172a"
        self.output.text_color = "#22c55e"
        self.output.font = ("Menlo", 13)
        self.output.editable = False
        self.add_subview(self.output)

        self.input = ui.TextField()
        self.input.placeholder = "Escribe aquí..."
        self.input.background_color = "#ffffff"
        self.input.text_color = "#000000"
        self.input.corner_radius = 10
        self.add_subview(self.input)

        self.btn_send = ui.Button(title="Enviar")
        self.btn_send.background_color = "#22c55e"
        self.btn_send.tint_color = "#000000"
        self.btn_send.corner_radius = 10
        self.btn_send.action = self.enviar
        self.add_subview(self.btn_send)

        self.btn_more = ui.Button(title="Más información")
        self.btn_more.background_color = "#8b5cf6"
        self.btn_more.tint_color = "#ffffff"
        self.btn_more.corner_radius = 10
        self.btn_more.action = self.mas_informacion
        self.add_subview(self.btn_more)

        self.btn_voice = ui.Button(title="🔊 Voz")
        self.btn_voice.background_color = "#3b82f6"
        self.btn_voice.tint_color = "#ffffff"
        self.btn_voice.corner_radius = 10
        self.btn_voice.action = self.hablar
        self.add_subview(self.btn_voice)

        self.btn_file = ui.Button(title="📂 Archivo")
        self.btn_file.background_color = "#f59e0b"
        self.btn_file.tint_color = "#000000"
        self.btn_file.corner_radius = 10
        self.btn_file.action = self.cargar
        self.add_subview(self.btn_file)

        self.btn_export = ui.Button(title="📝 Exportar TXT")
        self.btn_export.background_color = "#14b8a6"
        self.btn_export.tint_color = "#000000"
        self.btn_export.corner_radius = 10
        self.btn_export.action = self.exportar_txt
        self.add_subview(self.btn_export)

        self.btn_start = ui.Button(title="▶ Iniciar auto")
        self.btn_start.background_color = "#a855f7"
        self.btn_start.tint_color = "#ffffff"
        self.btn_start.corner_radius = 10
        self.btn_start.action = self.iniciar_auto
        self.add_subview(self.btn_start)

        self.btn_stop = ui.Button(title="■ Detener auto")
        self.btn_stop.background_color = "#ef4444"
        self.btn_stop.tint_color = "#ffffff"
        self.btn_stop.corner_radius = 10
        self.btn_stop.action = self.detener_auto
        self.add_subview(self.btn_stop)

        self.btn_scene = ui.Button(title="🎬 Siguiente escena")
        self.btn_scene.background_color = "#06b6d4"
        self.btn_scene.tint_color = "#000000"
        self.btn_scene.corner_radius = 10
        self.btn_scene.action = self.siguiente_escena
        self.add_subview(self.btn_scene)

        self.btn_math = ui.Button(title="🧮 Resolver math")
        self.btn_math.background_color = "#84cc16"
        self.btn_math.tint_color = "#000000"
        self.btn_math.corner_radius = 10
        self.btn_math.action = self.resolver_math_boton
        self.add_subview(self.btn_math)

        self.btn_clear = ui.Button(title="🧹 Limpiar")
        self.btn_clear.background_color = "#ef4444"
        self.btn_clear.tint_color = "#ffffff"
        self.btn_clear.corner_radius = 10
        self.btn_clear.action = self.limpiar_chat
        self.add_subview(self.btn_clear)

        self.status = ui.Label()
        self.status.text_color = "#cbd5e1"
        self.status.text = "Estado: Activo 🧠"
        self.add_subview(self.status)

        self.progress = ui.Label()
        self.progress.text_color = "#94a3b8"
        self.progress.text = "Progreso: listo"
        self.add_subview(self.progress)

        self.output.text = (
            "🤖 Hola, soy Kayro IA.\n"
            "Estoy lista para ayudarte con información, historias, recetas, clima,\n"
            "programación, biografías y mucho más.\n"
            "También puedo aprender de archivos y exportar texto a TXT.\n"
        )

    def layout(self):
        w = self.width
        h = self.height

        self.output.frame = (10, 10, w - 20, h - 410)
        self.input.frame = (10, h - 385, w - 20, 42)

        btn_w = (w - 50) / 4
        y1 = h - 330
        y2 = h - 280
        y3 = h - 230

        self.btn_send.frame = (10, y1, btn_w, 40)
        self.btn_more.frame = (20 + btn_w, y1, btn_w, 40)
        self.btn_voice.frame = (30 + btn_w * 2, y1, btn_w, 40)
        self.btn_file.frame = (40 + btn_w * 3, y1, btn_w, 40)

        self.btn_export.frame = (10, y2, w - 20, 40)

        self.btn_start.frame = (10, y3, btn_w, 40)
        self.btn_stop.frame = (20 + btn_w, y3, btn_w, 40)
        self.btn_scene.frame = (30 + btn_w * 2, y3, btn_w, 40)
        self.btn_math.frame = (40 + btn_w * 3, y3, btn_w, 40)
        self.btn_clear.frame = (10, h - 180, w - 20, 40)
        self.status.frame = (10, h - 110, w - 20, 22)
        self.progress.frame = (10, h - 86, w - 20, 22)

    def append_output(self, text):
        self.output.text += "\n" + text + "\n"
        try:
            self.output.selected_range = (len(self.output.text), 0)
        except Exception:
            pass

    def enviar(self, sender):
        user = self.input.text.strip()
        if not user:
            return

        add_chat_turn("user", user)

        try:
            response = interpret_input(user)
            add_chat_turn("assistant", response)
            self.append_output(f"🧑 Tú: {user}\n🤖 Kayro: {response}")
            self.status.text = f"Estado: {detect_expert_mode(user).capitalize()} ⚡"
            save_brain()
        except Exception as e:
            self.append_output(
                f"🧑 Tú: {user}\n"
                f"🤖 Kayro: Ocurrió un error.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                f"{traceback.format_exc()}"
            )
            self.status.text = "Estado: Error detectado ⚠️"

        self.input.text = ""

    def mas_informacion(self, sender):
        response = get_next_long_chunk()
        if not response:
            response = "No tengo más contenido guardado para expandir ahora mismo. Primero pídele información sobre un tema."
        add_chat_turn("user", "[Botón Más información]")
        add_chat_turn("assistant", response)
        self.append_output(f"🧑 Tú: [Más información]\n🤖 Kayro: {response}")
        save_brain()

    def hablar(self, sender):
        speak_text(self.output.text[-1800:])

    def cargar(self, sender):
        path = dialogs.pick_document()
        if path:
            msg = learn_file(path)
            self.append_output(f"🤖 Kayro: {msg}")
            self.status.text = "Estado: Archivo aprendido 📚"

    def exportar_txt(self, sender):
        filepath, message = export_last_text_to_txt()
        self.append_output(f"🤖 Kayro: {message}")
        if filepath:
            self.status.text = "Estado: TXT exportado 📝"
        else:
            self.status.text = "Estado: No se pudo exportar"

    def iniciar_auto(self, sender):
        if self.auto_running:
            self.append_output("Kayro ya está autoaprendiendo.")
            return

        self.auto_running = True
        self.auto_session_learned = []
        self.auto_cycle_count = 0
        self.status.text = "Estado: Aprendiendo... 🧠"
        self.progress.text = "Progreso: iniciando"
        self.append_output("▶ Autoaprendizaje continuo iniciado.")

        threading.Thread(target=self.auto_loop, daemon=True).start()

    def auto_loop(self):
        while self.auto_running:
            self.auto_cycle_count += 1
            delay = 30 if self.auto_cycle_count < 10 else 60
            self.progress.text = f"Progreso: ciclo {self.auto_cycle_count}"

            try:
                learned = auto_learn_batch_parallel()
                nuevos = [x for x in learned if x not in self.auto_session_learned]
                self.auto_session_learned.extend(nuevos)

                if nuevos:
                    self.append_output("🧠 Aprendizaje nuevo:\n" + "\n".join(nuevos))
                else:
                    self.append_output("🔄 Sin contenido nuevo")
            except Exception as e:
                self.append_output(f"Error en autoaprendizaje: {e}")

            total_sleep = 0
            while self.auto_running and total_sleep < delay:
                time.sleep(1)
                total_sleep += 1

    def detener_auto(self, sender):
        if not self.auto_running:
            self.append_output("El autoaprendizaje no está activo.")
            return

        self.auto_running = False
        self.status.text = "Estado: Autoaprendizaje detenido ⏸"
        self.progress.text = "Progreso: detenido"

        if self.auto_session_learned:
            resumen = "■ Autoaprendizaje detenido.\n\nEsto aprendió Kayro en esta sesión:\n\n"
            resumen += "\n".join(f"- {x}" for x in self.auto_session_learned)
        else:
            resumen = "■ Autoaprendizaje detenido.\n\nNo hubo aprendizajes nuevos."

        self.append_output(resumen)
        save_brain()

    def siguiente_escena(self, sender):
        response = continue_novel_scene()
        self.append_output(f"🤖 Kayro: {response}")
        save_brain()

    def resolver_math_boton(self, sender):
        expr = self.input.text.strip()
        if not expr:
            self.append_output("Escribe una operación en la caja primero.")
            return
        response = solve_math(expr)
        self.append_output(f"🧑 Tú: {expr}\n🤖 Kayro: {response}")
        self.input.text = ""
        save_brain()

    def limpiar_chat(self, sender):
        self.output.text = "🤖 Hola, soy Kayro IA.\nChat reiniciado.\n"

        BRAIN["chat"]["history"] = []
        BRAIN["chat"]["last_full_text"] = ""
        BRAIN["chat"]["last_full_title"] = ""
        BRAIN["chat"]["last_full_index"] = 0
        BRAIN["chat"]["last_mode"] = ""
        BRAIN["chat"]["last_subject"] = ""
        BRAIN["chat"]["last_topic"] = ""

        save_brain()

        self.status.text = "Estado: Chat limpio 🧹"


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    save_brain()
    KayroApp().present("fullscreen")

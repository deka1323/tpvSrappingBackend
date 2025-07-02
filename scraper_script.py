# scraper_script.py
import os
import time
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from openai import OpenAI
from dotenv import load_dotenv
import tiktoken
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from Flask_Backend_Supabase import News, Base

# === Load environment variables ===
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = "gpt-4o"
ARTICLE_LIMIT = 10
TODAY_DATE = datetime.today().strftime("%d/%m/%Y")

client = OpenAI(api_key=OPENAI_API_KEY)
tokenizer = tiktoken.encoding_for_model(MODEL_NAME)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def count_tokens(text):
    return len(tokenizer.encode(text))

def estimate_cost(input_tokens, output_tokens):
    return round((input_tokens * 0.005 + output_tokens * 0.015) / 1000, 4)

def rewrite_with_gpt(content):
    prompt = (
        "Rewrite the following news article professionally. "
        "Respond strictly in this JSON format:\n\n"
        '{\n  "title": "<title within 64 characters>",\n'
        '  "summary": "<summary within 348 characters>",\n'
        '  "rewritten_article": "<professionally rewritten full article>"\n}\n\n'
        f"Original Article:\n{content}"
    )
    input_tokens = count_tokens(prompt)
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Respond with valid JSON only. No markdown or ``` formatting."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        output_text = response.choices[0].message.content.strip()
        output_tokens = count_tokens(output_text)
        cost = estimate_cost(input_tokens, output_tokens)
        return output_text, input_tokens, output_tokens, cost
    except Exception as e:
        return f"Error summarizing: {e}", 0, 0, 0

def parse_gpt_response(response_text):
    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()
        parsed = json.loads(cleaned)
        return parsed.get("title", ""), parsed.get("summary", ""), parsed.get("rewritten_article", "")
    except Exception as e:
        return "", "", ""

def get_driver():
    options = Options()
    options.add_argument("--headless")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def url_exists(session, url):
    return session.query(News).filter_by(url=url).first() is not None

def run_adda247_scraper():
    print("📰 Running Adda247 scraper...")
    driver = get_driver()
    BASE_URL = "https://currentaffairs.adda247.com"
    driver.get(BASE_URL)
    time.sleep(3)
    soup = BeautifulSoup(driver.page_source, "lxml")

    articles = []
    for item in soup.select("li"):
        link_tag = item.select_one(".desc a")
        if link_tag:
            articles.append({"url": link_tag["href"], "title": link_tag.get_text(strip=True)})

    for li in soup.select("ul.lcp_catlist li"):
        link_tag = li.select_one("a")
        if link_tag:
            articles.append({"url": link_tag["href"], "title": link_tag.get_text(strip=True)})

    session = SessionLocal()

    for article in articles[:ARTICLE_LIMIT]:
        if url_exists(session, article["url"]):
            print(f"⏭ Skipping duplicate: {article['url']}")
            continue
        try:
            driver.get(article["url"])
            time.sleep(2)
            soup = BeautifulSoup(driver.page_source, "lxml")
            container = soup.select_one("div.entry-content") or soup
            content = []
            for tag in container.find_all(["h2", "h3", "p", "ul", "ol"]):
                if tag.name in ["h2", "h3"]:
                    content.append(f"\n{tag.get_text(strip=True)}\n")
                elif tag.name == "p":
                    content.append(tag.get_text(strip=True))
                elif tag.name in ["ul", "ol"]:
                    content.extend(f"- {li.get_text(strip=True)}" for li in tag.find_all("li"))
            full_text = "\n".join(content).strip()

            img_tag = soup.select_one("div.site-featured-image img") or container.select_one("img")
            image_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else ""

            gpt_text, input_t, output_t, cost = rewrite_with_gpt(full_text)
            title, summary, rewritten = parse_gpt_response(gpt_text)

            news_entry = News(
                url=article["url"],
                scraped_title=article["title"],
                title=title,
                summary=summary,
                image_url=image_url,
                scraped_text=full_text,
                rewritten_article=rewritten,
                input_tokens=str(input_t),
                output_tokens=str(output_t),
                cost=str(cost),
                source="Adda247",
                date=TODAY_DATE
            )
            session.add(news_entry)
            session.commit()
            print(f"✅ Added: {title}")
        except Exception as e:
            print(f"❌ Error: {e}")

    session.close()
    driver.quit()

def run_nextias_scraper():
    print("📰 Running NextIAS scraper...")
    session = SessionLocal()
    driver = get_driver()

    for i in range(5):
        check_date = datetime.today() - timedelta(days=i)
        url = f"https://www.nextias.com/ca/current-affairs/{check_date.strftime('%d-%m-%Y')}"
        print(f"🔍 Checking: {url}")
        driver.get(url)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "lxml")
        if soup.select_one("div.error404"):
            continue

        anchors = soup.select("div.row.card-text.entry-meta > a")
        articles = [{"title": a.get_text(strip=True), "url": a["href"]} for a in anchors]

        for article in articles[:ARTICLE_LIMIT]:
            if url_exists(session, article["url"]):
                print(f"⏭ Skipping duplicate: {article['url']}")
                continue
            try:
                driver.get(article["url"])
                time.sleep(2)
                inner_soup = BeautifulSoup(driver.page_source, "lxml")
                content_div = inner_soup.select_one("div.entry-content")
                full_text = content_div.get_text(separator="\n", strip=True) if content_div else ""

                gpt_text, input_t, output_t, cost = rewrite_with_gpt(full_text)
                title, summary, rewritten = parse_gpt_response(gpt_text)

                news_entry = News(
                    url=article["url"],
                    scraped_title=article["title"],
                    title=title,
                    summary=summary,
                    image_url="",
                    scraped_text=full_text,
                    rewritten_article=rewritten,
                    input_tokens=str(input_t),
                    output_tokens=str(output_t),
                    cost=str(cost),
                    source="NextIAS",
                    date=TODAY_DATE
                )
                session.add(news_entry)
                session.commit()
                print(f"✅ Added: {title}")
            except Exception as e:
                print(f"❌ Error: {e}")
        break  # break after first valid date found

    session.close()
    driver.quit()

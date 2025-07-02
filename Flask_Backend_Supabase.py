from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from datetime import datetime
from sqlalchemy.pool import NullPool

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "your_secret_token")

# Flask app setup
app = Flask(__name__)
CORS(app)

# SQLAlchemy 
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool  
)
# engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class News(Base):
    __tablename__ = 'news'
    id = Column(Integer, primary_key=True, index=True)
    url = Column(Text)
    scraped_title = Column(Text)
    title = Column(Text)
    summary = Column(Text)
    image_url = Column(Text)
    scraped_text = Column(Text)
    rewritten_article = Column(Text)
    input_tokens = Column(String)
    output_tokens = Column(String)
    cost = Column(String)
    source = Column(String)
    date = Column(String)

Base.metadata.create_all(bind=engine)

@app.route("/add", methods=["POST"])
def add_article():
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json()
        session = SessionLocal()
        article = News(**data)
        session.add(article)
        session.commit()
        session.close()
        return jsonify({"status": "Article added to DB"})
    except Exception as e:
        return jsonify({"error": f"DB Error: {str(e)}"})

@app.route("/news-by-date")
def news_by_date():
    date = request.args.get("date")
    if not date:
        return jsonify([])
    session = SessionLocal()
    results = session.query(News).filter_by(date=date).all()
    session.close()
    return jsonify([
        {
            "title": r.title,
            "summary": r.summary,
            "source": r.source,
            "url": r.url,
            "rewritten_article": r.rewritten_article,
            "imageUrl": r.image_url,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "scraped_title": r.scraped_title,
            "scraped_text": r.scraped_text,
            "date": r.date
        } for r in results
    ])

@app.route("/scraping-status")
def scraping_status():
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "Missing date parameter"}), 400

    session = SessionLocal()
    count = session.query(func.count(News.id)).filter_by(date=date).scalar()
    session.close()
    return jsonify({
        "scraped": count > 0,
        "date": date,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "articles_count": count
    })

@app.route("/run-scraper", methods=["POST"])
def run_scraper():
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        from scraper_script import run_adda247_scraper, run_nextias_scraper
        run_adda247_scraper()
        run_nextias_scraper()
        return jsonify({"status": "Scraper completed successfully"})
    except Exception as e:
        return jsonify({"error": f"Scraper failed: {str(e)}"})

if __name__ == "__main__":
    app.run(debug=True)

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./scraper.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class ScrapedProduct(Base):
    __tablename__ = "scraped_products"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True)
    scraper_type = Column(String) # sodimac, falabella, construmart
    sku = Column(String, index=True)
    store_id = Column(String)
    store_name = Column(String)
    
    # Datos scrapeados
    brand = Column(String)
    description = Column(String)
    price_normal = Column(String)
    price_internet = Column(String)
    price_cmr = Column(String)
    price_wholesale = Column(String)
    discount_pct = Column(String)
    url = Column(String)
    
    scraped_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)
    
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

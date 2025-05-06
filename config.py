import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import sys

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Database configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "NDyuFEyzHYHZxwGelhLhVJrnMBLtcKfr")
POSTGRES_DB = os.getenv("POSTGRES_DB", "railway")
PGHOST = os.getenv("PGHOST", "localhost")
PGPORT = os.getenv("PGPORT", "5432")

# Construct database URL
DATABASE_URL = os.getenv("DATABASE_URL", 
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{PGHOST}:{PGPORT}/{POSTGRES_DB}")

# SQLAlchemy configuration
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# SSL configuration
SSL_CERT_DAYS = int(os.getenv("SSL_CERT_DAYS", "820"))

# Railway specific configuration
RAILWAY_DEPLOYMENT_DRAINING_SECONDS = int(os.getenv("RAILWAY_DEPLOYMENT_DRAINING_SECONDS", "60"))
PGDATA = os.getenv("PGDATA", "/var/lib/postgresql/data/pgdata")

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development") 
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from sqlalchemy.exc import OperationalError

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

def get_database_url():
    """Get database URL with proper formatting"""
    # Try to get the full DATABASE_URL first
    database_url = os.getenv("DATABASE_URL")
    
    if database_url:
        # If DATABASE_URL starts with postgres://, change it to postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    
    # Fallback to individual components
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "NDyuFEyzHYHZxwGelhLhVJrnMBLtcKfr")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "railway")
    PGHOST = os.getenv("PGHOST", "localhost")
    PGPORT = os.getenv("PGPORT", "5432")
    
    return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{PGHOST}:{PGPORT}/{POSTGRES_DB}"

# Get database URL
DATABASE_URL = get_database_url()

logger.info(f"Database URL format: {'postgresql://' in DATABASE_URL}")
logger.info(f"Database host: {os.getenv('PGHOST', 'localhost')}")
logger.info(f"Database port: {os.getenv('PGPORT', '5432')}")
logger.info(f"Database name: {os.getenv('POSTGRES_DB', 'railway')}")

def create_db_engine(max_retries=5, retry_delay=5):
    """Create database engine with retry logic"""
    for attempt in range(max_retries):
        try:
            engine = create_engine(
                DATABASE_URL,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                echo=True,  # Enable SQL query logging
                pool_pre_ping=True,  # Enable connection health checks
                connect_args={
                    "connect_timeout": 10,  # Connection timeout in seconds
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5
                }
            )
            
            # Test the connection
            with engine.connect() as connection:
                connection.execute("SELECT 1")
                logger.info("Database connection test successful")
                return engine
                
        except OperationalError as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database connection attempt {attempt + 1} failed: {str(e)}")
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts")
                raise

# Create engine with retry logic
engine = create_db_engine()

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
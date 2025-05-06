import requests
from bs4 import BeautifulSoup
import pandas as pd
from sqlalchemy.orm import Session
from models import RegularJob, FreshersJob, InternshipJob
from config import get_db, logger, engine
from sqlalchemy import inspect
import time
from requests.exceptions import RequestException
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, Dict, Any, Type, List
import backoff
from datetime import datetime
from urllib.parse import urljoin
import html
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue
import signal
import sys
import json
import os
from pathlib import Path
import atexit
import tempfile
import shutil
import psutil
import pickle
from enum import Enum
import traceback

# Constants
STATE_FILE = "scraper_state.json"
TEMP_STATE_FILE = "scraper_state_temp.json"
BACKUP_STATE_FILE = "scraper_state_backup.json"
MAX_RETRIES = 3
BATCH_SIZE = 10
DELAY_BETWEEN_PAGES = 2
DELAY_BETWEEN_SOURCES = 2
AUTO_SAVE_INTERVAL = 60  # Save state every 60 seconds
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_DELAY = 5  # seconds

class ScraperState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    RECOVERING = "recovering"
    COMPLETED = "completed"

class PauseStrategy(Enum):
    IMMEDIATE = "immediate"  # Stop immediately
    GRACEFUL = "graceful"   # Complete current batch
    SCHEDULED = "scheduled" # Pause at next checkpoint

# Global state for tracking scraping progress
scraping_status = {
    "is_running": False,
    "is_paused": False,
    "current_source": None,
    "state": ScraperState.IDLE.value,
    "pause_strategy": PauseStrategy.GRACEFUL.value,
    "recovery_attempts": 0,
    "progress": {
        "Regular": {
            "status": "pending",
            "pages_completed": 0,
            "total_pages": 0,
            "jobs_scraped": 0,
            "last_successful_page": 0,
            "errors": [],
            "start_time": None,
            "end_time": None,
            "last_save_time": None,
            "checkpoints": [],
            "current_page": 0,
            "current_job": None,
            "current_operation": None,
            "page_progress": {
                "total_jobs_found": 0,
                "jobs_processed": 0,
                "jobs_saved": 0,
                "errors": 0
            },
            "last_update": None
        },
        "Freshers": {
            "status": "pending",
            "pages_completed": 0,
            "total_pages": 0,
            "jobs_scraped": 0,
            "last_successful_page": 0,
            "errors": [],
            "start_time": None,
            "end_time": None,
            "last_save_time": None,
            "checkpoints": [],
            "current_page": 0,
            "current_job": None,
            "current_operation": None,
            "page_progress": {
                "total_jobs_found": 0,
                "jobs_processed": 0,
                "jobs_saved": 0,
                "errors": 0
            },
            "last_update": None
        },
        "Internships": {
            "status": "pending",
            "pages_completed": 0,
            "total_pages": 0,
            "jobs_scraped": 0,
            "last_successful_page": 0,
            "errors": [],
            "start_time": None,
            "end_time": None,
            "last_save_time": None,
            "checkpoints": [],
            "current_page": 0,
            "current_job": None,
            "current_operation": None,
            "page_progress": {
                "total_jobs_found": 0,
                "jobs_processed": 0,
                "jobs_saved": 0,
                "errors": 0
            },
            "last_update": None
        }
    },
    "start_time": None,
    "end_time": None,
    "error": None,
    "total_jobs_scraped": 0,
    "last_updated": None,
    "last_save_time": None,
    "interrupted": False,
    "system_info": {
        "memory_usage": None,
        "cpu_usage": None,
        "disk_usage": None
    },
    "scraping_stats": {
        "total_pages_scraped": 0,
        "total_jobs_found": 0,
        "total_jobs_saved": 0,
        "total_errors": 0,
        "average_response_time": 0,
        "start_time": None,
        "end_time": None,
        "elapsed_time": None
    }
}

# Thread-safe state management
state_lock = threading.Lock()
auto_save_thread = None
stop_auto_save = threading.Event()
pause_event = threading.Event()
resume_event = threading.Event()

def update_system_info():
    """Update system resource usage information"""
    try:
        process = psutil.Process()
        with state_lock:
            scraping_status["system_info"] = {
                "memory_usage": process.memory_info().rss / 1024 / 1024,  # MB
                "cpu_usage": process.cpu_percent(),
                "disk_usage": psutil.disk_usage('/').percent
            }
    except Exception as e:
        logger.error(f"Error updating system info: {str(e)}")

def create_checkpoint(source_type: str, page: int, jobs_scraped: int):
    """Create a checkpoint for recovery"""
    checkpoint = {
        "timestamp": datetime.utcnow(),
        "page": page,
        "jobs_scraped": jobs_scraped,
        "system_info": scraping_status["system_info"].copy()
    }
    with state_lock:
        scraping_status["progress"][source_type]["checkpoints"].append(checkpoint)
    atomic_save_state()

def atomic_save_state():
    """Save state atomically using a temporary file"""
    try:
        with state_lock:
            # Update system info before saving
            update_system_info()
            
            # Create temporary file
            temp_dir = Path("state")
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / TEMP_STATE_FILE
            
            # Write to temporary file
            with open(temp_file, 'w') as f:
                json.dump(scraping_status, f, default=str)
            
            # Create backup of current state
            if (temp_dir / STATE_FILE).exists():
                shutil.copy2(temp_dir / STATE_FILE, temp_dir / BACKUP_STATE_FILE)
            
            # Atomic rename
            target_file = temp_dir / STATE_FILE
            shutil.move(str(temp_file), str(target_file))
            
            # Update last save time
            scraping_status["last_save_time"] = datetime.utcnow()
            for source in scraping_status["progress"].values():
                source["last_save_time"] = datetime.utcnow()
            
            logger.info("Scraping state saved successfully")
    except Exception as e:
        logger.error(f"Error saving scraping state: {str(e)}")

def auto_save_worker():
    """Background thread for periodic state saving"""
    while not stop_auto_save.is_set():
        time.sleep(AUTO_SAVE_INTERVAL)
        if scraping_status["is_running"] and not scraping_status["is_paused"]:
            atomic_save_state()

def start_auto_save():
    """Start the auto-save thread"""
    global auto_save_thread
    stop_auto_save.clear()
    auto_save_thread = threading.Thread(target=auto_save_worker, daemon=True)
    auto_save_thread.start()

def stop_auto_save_thread():
    """Stop the auto-save thread"""
    if auto_save_thread and auto_save_thread.is_alive():
        stop_auto_save.set()
        auto_save_thread.join()

def load_state():
    """Load scraping state from file with enhanced error handling"""
    try:
        state_dir = Path("state")
        state_file = state_dir / STATE_FILE
        backup_file = state_dir / BACKUP_STATE_FILE
        
        # Try to load main state file
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                return convert_state_timestamps(state)
            except Exception as e:
                logger.error(f"Error loading main state file: {str(e)}")
        
        # If main state file fails, try backup
        if backup_file.exists():
            try:
                with open(backup_file, 'r') as f:
                    state = json.load(f)
                logger.info("Loaded state from backup file")
                return convert_state_timestamps(state)
            except Exception as e:
                logger.error(f"Error loading backup state file: {str(e)}")
        
        return None
    except Exception as e:
        logger.error(f"Error in load_state: {str(e)}")
        return None

def convert_state_timestamps(state):
    """Convert string timestamps to datetime objects"""
    try:
        for source in state["progress"].values():
            for field in ["start_time", "end_time", "last_save_time"]:
                if source.get(field):
                    source[field] = datetime.fromisoformat(source[field])
            # Convert checkpoint timestamps
            for checkpoint in source.get("checkpoints", []):
                if checkpoint.get("timestamp"):
                    checkpoint["timestamp"] = datetime.fromisoformat(checkpoint["timestamp"])
        
        for field in ["start_time", "end_time", "last_updated", "last_save_time"]:
            if state.get(field):
                state[field] = datetime.fromisoformat(state[field])
        
        return state
    except Exception as e:
        logger.error(f"Error converting timestamps: {str(e)}")
        return None

def handle_interrupt(signum, frame):
    """Handle interruption signals"""
    logger.info(f"Received signal {signum}, saving state and stopping...")
    with state_lock:
        scraping_status["is_running"] = False
        scraping_status["interrupted"] = True
        scraping_status["end_time"] = datetime.utcnow()
        scraping_status["state"] = ScraperState.ERROR.value
    atomic_save_state()
    stop_auto_save_thread()
    sys.exit(0)

def handle_pause(signum, frame):
    """Handle pause signal with strategy"""
    logger.info("Pausing scraping...")
    with state_lock:
        scraping_status["is_paused"] = True
        scraping_status["state"] = ScraperState.PAUSED.value
    atomic_save_state()
    pause_event.set()

def handle_resume(signum, frame):
    """Handle resume signal"""
    logger.info("Resuming scraping...")
    with state_lock:
        scraping_status["is_paused"] = False
        scraping_status["state"] = ScraperState.RUNNING.value
    atomic_save_state()
    resume_event.set()

def handle_reload(signum, frame):
    """Handle reload signal (SIGHUP)"""
    logger.info("Reloading configuration...")
    atomic_save_state()
    # Add any configuration reload logic here

def handle_user_defined(signum, frame):
    """Handle user-defined signals"""
    logger.info(f"Received user-defined signal {signum}")
    atomic_save_state()

# Register signal handlers
signal.signal(signal.SIGINT, handle_interrupt)   # Ctrl+C
signal.signal(signal.SIGTERM, handle_interrupt)  # Termination
signal.signal(signal.SIGUSR1, handle_pause)     # Pause
signal.signal(signal.SIGUSR2, handle_resume)    # Resume
signal.signal(signal.SIGHUP, handle_reload)     # Reload
signal.signal(signal.SIGUSR1, handle_user_defined)  # User-defined 1
signal.signal(signal.SIGUSR2, handle_user_defined)  # User-defined 2

# Register exit handler
atexit.register(lambda: atomic_save_state())

def pause_scraping(strategy: PauseStrategy = PauseStrategy.GRACEFUL):
    """Pause the scraping process with specified strategy"""
    with state_lock:
        scraping_status["pause_strategy"] = strategy.value
    handle_pause(None, None)

def resume_scraping():
    """Resume the scraping process"""
    handle_resume(None, None)

def recover_from_state():
    """Recover from previous state with enhanced error handling"""
    try:
        state = load_state()
        if not state:
            logger.error("No valid state found for recovery")
            return False
        
        with state_lock:
            scraping_status.update(state)
            scraping_status["state"] = ScraperState.RECOVERING.value
            scraping_status["recovery_attempts"] += 1
        
        if scraping_status["recovery_attempts"] > MAX_RECOVERY_ATTEMPTS:
            logger.error("Maximum recovery attempts exceeded")
            return False
        
        # Verify system resources
        update_system_info()
        if scraping_status["system_info"]["memory_usage"] > 1000:  # 1GB
            logger.warning("High memory usage detected")
        
        return True
    except Exception as e:
        logger.error(f"Error in recovery: {str(e)}")
        return False

def ensure_tables_exist():
    """Ensure all required tables exist in the database"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    required_tables = ['regular_jobs', 'freshers_jobs', 'internship_jobs']
    
    for table in required_tables:
        if table not in existing_tables:
            logger.info(f"Creating table: {table}")
            if table == 'regular_jobs':
                RegularJob.__table__.create(engine)
            elif table == 'freshers_jobs':
                FreshersJob.__table__.create(engine)
            elif table == 'internship_jobs':
                InternshipJob.__table__.create(engine)

def clean_salary(salary: str) -> str:
    """Clean salary string"""
    if not salary:
        return ""
    return salary.replace("\u20b9", "INR").replace("₹", "INR").replace("?", "INR").strip()

def clean_text(text: str) -> str:
    """Clean text string"""
    return html.unescape(text.strip()) if text else ""

@backoff.on_exception(
    backoff.expo,
    (RequestException, SQLAlchemyError),
    max_tries=MAX_RETRIES,
    max_time=60,
    giveup=lambda e: isinstance(e, (ValueError, AttributeError))
)
def make_request(url: str) -> requests.Response:
    """Make HTTP request with enhanced retry logic"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response

def extract_job_details(job_element: BeautifulSoup, base_url: str) -> Optional[Dict[str, Any]]:
    """Extract job details from HTML element with enhanced error handling"""
    try:
        # Get the job title
        title = clean_text(job_element.select_one("h2.text-lg").text) if job_element.select_one("h2.text-lg") else ""
        if not title:
            logger.warning("Skipping job with no title")
            return None
        
        # Get company and location
        company_location = clean_text(job_element.select_one("p.text-gray-600").text) if job_element.select_one("p.text-gray-600") else ""
        
        # Get salary
        salary_raw = clean_text(job_element.select_one("p.text-green-600").text) if job_element.select_one("p.text-green-600") else ""
        salary = clean_salary(salary_raw)
        
        # Get posted date
        posted_date = clean_text(job_element.select_one("p.text-gray-500").text) if job_element.select_one("p.text-gray-500") else ""
        
        # Get tags (years and job type)
        tags = job_element.select("div.mt-2 span.text-sm")
        years = clean_text(tags[0].text) if len(tags) > 0 else ""
        job_type = clean_text(tags[1].text) if len(tags) > 1 else ""
        
        # Get skills
        skills_list = [clean_text(s.text) for s in job_element.select("div.flex-wrap.gap-2.mt-3 span")]
        skills = ", ".join(skills_list)
        
        # Get apply URL
        apply_button = job_element.select_one("a.bg-blue-600")
        apply_url = urljoin(base_url, apply_button["href"]) if apply_button and "href" in apply_button.attrs else ""
        
        # Get company logo
        img_tag = job_element.select_one("img.rounded-lg")
        logo_url = urljoin(base_url, img_tag["src"]) if img_tag and "src" in img_tag.attrs else ""
        
        return {
            'job_title': title,
            'company_location': company_location,
            'salary': salary,
            'job_type': job_type,
            'posted': posted_date,
            'skills': skills,
            'eligible_years': years,
            'apply_url': apply_url,
            'company_logo': logo_url,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
    except (AttributeError, KeyError) as e:
        logger.error(f"Error extracting job details: {str(e)}")
        return None

def get_job_model(source_type: str) -> Type:
    """Get the appropriate job model based on source type"""
    model_map = {
        "Regular": RegularJob,
        "Freshers": FreshersJob,
        "Internships": InternshipJob
    }
    return model_map.get(source_type)

def process_job_batch(jobs: List[Dict[str, Any]], db: Session, JobModel: Type) -> int:
    """Process a batch of jobs with error handling"""
    successful_jobs = 0
    for job_details in jobs:
        try:
            if not job_details:
                continue
            new_job = JobModel(**job_details)
            db.add(new_job)
            successful_jobs += 1
        except Exception as e:
            logger.error(f"Error processing job: {str(e)}")
            continue
    return successful_jobs

def update_page_progress(source_type: str, page: int, operation: str, job_title: Optional[str] = None):
    """Update the current page progress"""
    with state_lock:
        scraping_status["progress"][source_type]["current_page"] = page
        scraping_status["progress"][source_type]["current_operation"] = operation
        if job_title:
            scraping_status["progress"][source_type]["current_job"] = job_title
        scraping_status["progress"][source_type]["last_update"] = datetime.utcnow()
    atomic_save_state()

def update_page_stats(source_type: str, total_found: int, processed: int, saved: int, errors: int):
    """Update statistics for the current page"""
    with state_lock:
        scraping_status["progress"][source_type]["page_progress"] = {
            "total_jobs_found": total_found,
            "jobs_processed": processed,
            "jobs_saved": saved,
            "errors": errors
        }
        scraping_status["scraping_stats"]["total_jobs_found"] += total_found
        scraping_status["scraping_stats"]["total_jobs_saved"] += saved
        scraping_status["scraping_stats"]["total_errors"] += errors
    atomic_save_state()

def update_scraping_stats(response_time: float):
    """Update overall scraping statistics"""
    with state_lock:
        current_avg = scraping_status["scraping_stats"]["average_response_time"]
        total_pages = scraping_status["scraping_stats"]["total_pages_scraped"]
        scraping_status["scraping_stats"]["average_response_time"] = (
            (current_avg * total_pages + response_time) / (total_pages + 1)
        )
        scraping_status["scraping_stats"]["total_pages_scraped"] += 1
        scraping_status["scraping_stats"]["elapsed_time"] = (
            datetime.utcnow() - scraping_status["scraping_stats"]["start_time"]
        ).total_seconds()
    atomic_save_state()

def scrape_and_save_jobs(source_type: str) -> None:
    """Scrape and save jobs for a specific source type with enhanced progress tracking"""
    global scraping_status
    
    db = next(get_db())
    JobModel = get_job_model(source_type)
    
    if not JobModel:
        raise ValueError(f"Invalid source type: {source_type}")
    
    try:
        with state_lock:
            scraping_status["current_source"] = source_type
            scraping_status["progress"][source_type]["status"] = "in_progress"
            scraping_status["progress"][source_type]["start_time"] = datetime.utcnow()
            scraping_status["scraping_stats"]["start_time"] = datetime.utcnow()
        atomic_save_state()
        
        # Clear existing jobs for this source
        update_page_progress(source_type, 0, "Clearing existing jobs")
        db.query(JobModel).delete()
        db.commit()
        logger.info(f"Cleared existing {source_type} jobs")
        
        # Determine URL based on source type
        url_map = {
            "Regular": "https://www.talentd.in/jobs?page=",
            "Freshers": "https://www.talentd.in/jobs/freshers?page=",
            "Internships": "https://www.talentd.in/jobs/internships?page="
        }
        
        base_url = url_map[source_type]
        
        # Get first page to detect total pages
        update_page_progress(source_type, 1, "Detecting total pages")
        start_time = time.time()
        first_page = make_request(base_url + "1")
        response_time = time.time() - start_time
        update_scraping_stats(response_time)
        
        soup = BeautifulSoup(first_page.text, "html.parser")
        pagination = soup.select("div.hidden.sm\\:flex a[href*='page=']")
        last_page = max([int(a.text.strip()) for a in pagination if a.text.strip().isdigit()] or [1])
        
        with state_lock:
            scraping_status["progress"][source_type]["total_pages"] = last_page
        atomic_save_state()
        logger.info(f"Total pages detected for {source_type}: {last_page}")
        
        successful_jobs = 0
        for page in range(1, last_page + 1):
            # Check for pause with strategy
            if scraping_status["is_paused"]:
                if scraping_status["pause_strategy"] == PauseStrategy.IMMEDIATE.value:
                    break
                elif scraping_status["pause_strategy"] == PauseStrategy.GRACEFUL.value:
                    # Complete current batch
                    if job_details_batch:
                        batch_success = process_job_batch(job_details_batch, db, JobModel)
                        successful_jobs += batch_success
                        db.commit()
                        update_progress(source_type, page, batch_success)
                    break
                else:  # SCHEDULED
                    pause_event.wait()
                    pause_event.clear()
            
            if not scraping_status["is_running"]:
                logger.info(f"Scraping stopped for {source_type}")
                break
            
            # Create checkpoint every 5 pages
            if page % 5 == 0:
                create_checkpoint(source_type, page, successful_jobs)
            
            update_page_progress(source_type, page, "Fetching page")
            logger.info(f"Scraping page {page} of {last_page} for {source_type}...")
            
            try:
                start_time = time.time()
                response = make_request(base_url + str(page))
                response_time = time.time() - start_time
                update_scraping_stats(response_time)
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Find all job listings
                job_cards = soup.find_all("div", class_="!bg-white/80 backdrop-blur-sm rounded-xl border border-gray-200/50 p-4 hover:shadow-lg transition-all hover:border-blue-200/50")
                logger.info(f"Found {len(job_cards)} jobs on page {page}")
                
                # Process jobs in batches
                job_details_batch = []
                processed_jobs = 0
                saved_jobs = 0
                error_jobs = 0
                
                for job in job_cards:
                    update_page_progress(source_type, page, "Processing job", job.select_one("h2.text-lg").text if job.select_one("h2.text-lg") else "Unknown")
                    job_details = extract_job_details(job, base_url)
                    processed_jobs += 1
                    
                    if job_details:
                        job_details_batch.append(job_details)
                        saved_jobs += 1
                    else:
                        error_jobs += 1
                    
                    if len(job_details_batch) >= BATCH_SIZE:
                        batch_success = process_job_batch(job_details_batch, db, JobModel)
                        successful_jobs += batch_success
                        db.commit()
                        update_progress(source_type, page, batch_success)
                        job_details_batch = []
                
                # Process remaining jobs
                if job_details_batch:
                    batch_success = process_job_batch(job_details_batch, db, JobModel)
                    successful_jobs += batch_success
                    db.commit()
                    update_progress(source_type, page, batch_success)
                
                update_page_stats(source_type, len(job_cards), processed_jobs, saved_jobs, error_jobs)
                time.sleep(DELAY_BETWEEN_PAGES)
                
            except Exception as e:
                error_msg = f"Error processing page {page} for {source_type}: {str(e)}"
                logger.error(error_msg)
                update_progress(source_type, page, 0, error_msg)
                continue
        
        with state_lock:
            scraping_status["progress"][source_type]["status"] = "completed"
            scraping_status["progress"][source_type]["end_time"] = datetime.utcnow()
            scraping_status["state"] = ScraperState.COMPLETED.value
            scraping_status["scraping_stats"]["end_time"] = datetime.utcnow()
        atomic_save_state()
        logger.info(f"Successfully saved {successful_jobs} jobs for {source_type}")
                
    except Exception as e:
        with state_lock:
            scraping_status["progress"][source_type]["status"] = "failed"
            scraping_status["progress"][source_type]["end_time"] = datetime.utcnow()
            scraping_status["error"] = str(e)
            scraping_status["state"] = ScraperState.ERROR.value
        atomic_save_state()
        logger.error(f"Error scraping {source_type} jobs: {str(e)}")
        db.rollback()
        raise ScrapingError(f"Failed to scrape {source_type} jobs: {str(e)}")
    finally:
        db.close()

def run_all_scrapers() -> None:
    """Run scrapers for all job types with enhanced error handling"""
    global scraping_status
    
    try:
        # Try to recover from previous state
        if not recover_from_state():
            # Reset and initialize scraping status
            reset_scraping_status()
        
        with state_lock:
            scraping_status["is_running"] = True
            scraping_status["start_time"] = datetime.utcnow()
            scraping_status["state"] = ScraperState.RUNNING.value
        atomic_save_state()
        
        # Start auto-save thread
        start_auto_save()
        
        # Ensure all tables exist
        ensure_tables_exist()
        
        sources = ["Regular", "Freshers", "Internships"]
        for source in sources:
            if not scraping_status["is_running"]:
                break
            
            # Skip completed sources
            if scraping_status["progress"][source]["status"] == "completed":
                logger.info(f"Skipping completed source: {source}")
                continue
            
            try:
                logger.info(f"Starting scraper for {source} jobs")
                scrape_and_save_jobs(source)
                time.sleep(DELAY_BETWEEN_SOURCES)
            except ScrapingError as e:
                logger.error(f"Scraper failed for {source}: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in {source} scraper: {str(e)}")
                continue
        
        with state_lock:
            scraping_status["is_running"] = False
            scraping_status["end_time"] = datetime.utcnow()
            scraping_status["state"] = ScraperState.COMPLETED.value
        atomic_save_state()
        
    except Exception as e:
        with state_lock:
            scraping_status["is_running"] = False
            scraping_status["end_time"] = datetime.utcnow()
            scraping_status["error"] = str(e)
            scraping_status["state"] = ScraperState.ERROR.value
        atomic_save_state()
        logger.error(f"Fatal error in scraper: {str(e)}")
        raise
    finally:
        stop_auto_save_thread()

def stop_scraping():
    """Stop the scraping process"""
    handle_interrupt(None, None)

if __name__ == "__main__":
    try:
        run_all_scrapers()
    except Exception as e:
        logger.error(f"Fatal error in scraper: {str(e)}")
        raise 
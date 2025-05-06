from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from models import RegularJob, FreshersJob, InternshipJob, Base
from config import get_db, engine, logger
from pydantic import BaseModel, HttpUrl, validator
from datetime import datetime
import time
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from scraper import run_all_scrapers, get_scraping_status, stop_scraping
from request_tracker import request_tracker
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import os
import asyncio

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="HirePro Jobs API",
    description="API for accessing job listings from talentd.in",
    version="1.0.0"
)

# Add rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables with error handling
try:
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    logger.error(f"Error creating database tables: {str(e)}")
    raise

class JobResponse(BaseModel):
    id: int
    job_title: str
    company_location: str
    salary: str
    job_type: str
    posted: str
    skills: str
    eligible_years: str
    apply_url: HttpUrl
    company_logo: Optional[HttpUrl]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# Helper function for job queries
def get_filtered_jobs(db: Session, model_class, search: Optional[str] = None, location: Optional[str] = None):
    try:
        query = db.query(model_class)
        
        if search:
            search_terms = search.lower().split()
            for term in search_terms:
                query = query.filter(
                    (model_class.job_title.ilike(f"%{term}%")) |
                    (model_class.company_location.ilike(f"%{term}%")) |
                    (model_class.skills.ilike(f"%{term}%"))
                )
        
        if location:
            query = query.filter(model_class.company_location.ilike(f"%{location}%"))
        
        return query.all()
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_filtered_jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error occurred")

@app.middleware("http")
async def track_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    response_time = time.time() - start_time
    
    # Get client IP
    ip = request.client.host
    if "x-forwarded-for" in request.headers:
        ip = request.headers["x-forwarded-for"].split(",")[0]
    
    # Log the request
    request_tracker.log_request(
        endpoint=request.url.path,
        method=request.method,
        ip=ip,
        user_agent=request.headers.get("user-agent", "Unknown"),
        status_code=response.status_code,
        response_time=response_time
    )
    
    return response

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.get("/api/regular-jobs", response_model=List[JobResponse])
@limiter.limit("60/minute")
async def get_regular_jobs(
    request: Request,
    search: Optional[str] = Query(None, description="Search term for job title, company, or skills"),
    location: Optional[str] = Query(None, description="Filter by location"),
    db: Session = Depends(get_db)
):
    """
    Get regular jobs with optional search and location filters.
    Rate limited to 60 requests per minute.
    """
    try:
        jobs = get_filtered_jobs(db, RegularJob, search, location)
        logger.info(f"Retrieved {len(jobs)} regular jobs")
        return jobs
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving regular jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/freshers-jobs", response_model=List[JobResponse])
@limiter.limit("60/minute")
async def get_freshers_jobs(
    request: Request,
    search: Optional[str] = Query(None, description="Search term for job title, company, or skills"),
    location: Optional[str] = Query(None, description="Filter by location"),
    db: Session = Depends(get_db)
):
    """
    Get freshers jobs with optional search and location filters.
    Rate limited to 60 requests per minute.
    """
    try:
        jobs = get_filtered_jobs(db, FreshersJob, search, location)
        logger.info(f"Retrieved {len(jobs)} freshers jobs")
        return jobs
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving freshers jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/internships", response_model=List[JobResponse])
@limiter.limit("60/minute")
async def get_internships(
    request: Request,
    search: Optional[str] = Query(None, description="Search term for job title, company, or skills"),
    location: Optional[str] = Query(None, description="Filter by location"),
    db: Session = Depends(get_db)
):
    """
    Get internship jobs with optional search and location filters.
    Rate limited to 60 requests per minute.
    """
    try:
        jobs = get_filtered_jobs(db, InternshipJob, search, location)
        logger.info(f"Retrieved {len(jobs)} internship jobs")
        return jobs
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving internship jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/jobs/{job_id}", response_model=JobResponse)
@limiter.limit("60/minute")
async def get_job(
    request: Request,
    job_id: int,
    job_type: str = Query(..., description="Type of job (regular/freshers/internships)"),
    db: Session = Depends(get_db)
):
    """
    Get a specific job by ID and type.
    Rate limited to 60 requests per minute.
    """
    try:
        model_map = {
            "regular": RegularJob,
            "freshers": FreshersJob,
            "internships": InternshipJob
        }
        
        if job_type.lower() not in model_map:
            raise HTTPException(status_code=400, detail="Invalid job type")
            
        job = db.query(model_map[job_type.lower()]).filter(model_map[job_type.lower()].id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/scrape")
async def trigger_scrape():
    """Trigger job scraping in the background"""
    try:
        # Start scraping in background
        asyncio.create_task(run_all_scrapers())
        return {
            "status": "success",
            "message": "Scraping started in background",
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        logger.error(f"Error starting scrape: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start scraping: {str(e)}"
        )

@app.get("/api/scrape/status")
async def get_scrape_status():
    """Get the current status of the scraping process"""
    try:
        status = get_scraping_status()
        return {
            "is_running": status["is_running"],
            "is_paused": status["is_paused"],
            "state": status["state"],
            "current_source": status["current_source"],
            "progress": {
                source: {
                    "status": data["status"],
                    "pages_completed": data["pages_completed"],
                    "total_pages": data["total_pages"],
                    "jobs_scraped": data["jobs_scraped"],
                    "current_page": data["current_page"],
                    "current_job": data["current_job"],
                    "current_operation": data["current_operation"],
                    "page_progress": data["page_progress"],
                    "last_update": data["last_update"],
                    "start_time": data["start_time"],
                    "end_time": data["end_time"],
                    "errors": data["errors"]
                }
                for source, data in status["progress"].items()
            },
            "scraping_stats": {
                "total_pages_scraped": status["scraping_stats"]["total_pages_scraped"],
                "total_jobs_found": status["scraping_stats"]["total_jobs_found"],
                "total_jobs_saved": status["scraping_stats"]["total_jobs_saved"],
                "total_errors": status["scraping_stats"]["total_errors"],
                "average_response_time": round(status["scraping_stats"]["average_response_time"], 3),
                "start_time": status["scraping_stats"]["start_time"],
                "end_time": status["scraping_stats"]["end_time"],
                "elapsed_time": status["scraping_stats"]["elapsed_time"]
            },
            "system_info": status["system_info"],
            "error": status["error"]
        }
    except Exception as e:
        logger.error(f"Error getting scraper status: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting scraper status")

@app.get("/api/scrape/detailed-status")
async def get_detailed_scrape_status():
    """Get detailed status of the scraping process including per-page information"""
    try:
        status = get_scraping_status()
        detailed_status = {
            "overall": {
                "is_running": status["is_running"],
                "is_paused": status["is_paused"],
                "state": status["state"],
                "current_source": status["current_source"],
                "start_time": status["start_time"],
                "end_time": status["end_time"],
                "error": status["error"]
            },
            "sources": {
                source: {
                    "status": data["status"],
                    "progress": {
                        "pages": {
                            "completed": data["pages_completed"],
                            "total": data["total_pages"],
                            "current": data["current_page"],
                            "percentage": round((data["pages_completed"] / data["total_pages"] * 100) if data["total_pages"] > 0 else 0, 2)
                        },
                        "jobs": {
                            "scraped": data["jobs_scraped"],
                            "current_page": data["page_progress"],
                            "success_rate": round((data["jobs_scraped"] / (data["pages_completed"] * 20) * 100) if data["pages_completed"] > 0 else 0, 2)
                        },
                        "current_operation": {
                            "type": data["current_operation"],
                            "job": data["current_job"],
                            "last_update": data["last_update"]
                        }
                    },
                    "timing": {
                        "start_time": data["start_time"],
                        "end_time": data["end_time"],
                        "duration": (data["end_time"] - data["start_time"]).total_seconds() if data["end_time"] and data["start_time"] else None
                    },
                    "errors": data["errors"]
                }
                for source, data in status["progress"].items()
            },
            "statistics": {
                "pages": {
                    "total_scraped": status["scraping_stats"]["total_pages_scraped"],
                    "average_response_time": round(status["scraping_stats"]["average_response_time"], 3)
                },
                "jobs": {
                    "total_found": status["scraping_stats"]["total_jobs_found"],
                    "total_saved": status["scraping_stats"]["total_jobs_saved"],
                    "total_errors": status["scraping_stats"]["total_errors"],
                    "success_rate": round((status["scraping_stats"]["total_jobs_saved"] / status["scraping_stats"]["total_jobs_found"] * 100) if status["scraping_stats"]["total_jobs_found"] > 0 else 0, 2)
                },
                "timing": {
                    "start_time": status["scraping_stats"]["start_time"],
                    "end_time": status["scraping_stats"]["end_time"],
                    "elapsed_time": status["scraping_stats"]["elapsed_time"]
                }
            },
            "system": {
                "memory_usage": f"{round(status['system_info']['memory_usage'], 2)} MB" if status['system_info']['memory_usage'] else None,
                "cpu_usage": f"{round(status['system_info']['cpu_usage'], 2)}%" if status['system_info']['cpu_usage'] else None,
                "disk_usage": f"{round(status['system_info']['disk_usage'], 2)}%" if status['system_info']['disk_usage'] else None
            }
        }
        return detailed_status
    except Exception as e:
        logger.error(f"Error getting detailed scraper status: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting detailed scraper status")

@app.post("/api/scrape/stop")
async def stop_scrape():
    """Stop the current scraping operation"""
    stop_scraping()
    return {
        "status": "success",
        "message": "Scraping process stopped",
        "timestamp": datetime.utcnow()
    }

# New endpoints for request tracking and monitoring

@app.get("/api/stats/active-users")
async def get_active_users(time_window: int = 300):
    """Get active users in the last time_window seconds"""
    try:
        return request_tracker.get_active_users(time_window)
    except Exception as e:
        logger.error(f"Error getting active users: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting active users")

@app.get("/api/stats/endpoints")
async def get_endpoint_stats(time_window: int = 3600):
    """Get statistics for each endpoint"""
    try:
        return request_tracker.get_endpoint_stats(time_window)
    except Exception as e:
        logger.error(f"Error getting endpoint stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting endpoint stats")

@app.get("/api/stats/ip/{ip}")
async def get_ip_stats(ip: str, time_window: int = 3600):
    """Get statistics for a specific IP address"""
    try:
        return request_tracker.get_ip_stats(ip, time_window)
    except Exception as e:
        logger.error(f"Error getting IP stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting IP stats")

@app.get("/api/stats/scraper")
async def get_scraper_stats(time_window: int = 3600):
    """Get statistics specifically for scraper requests"""
    try:
        stats = request_tracker.get_endpoint_stats(time_window)
        scraper_stats = {
            endpoint: {
                'scraper_requests': data['scraper_requests'],
                'total_requests': data['total_requests'],
                'scraper_percentage': round(
                    (data['scraper_requests'] / data['total_requests'] * 100)
                    if data['total_requests'] > 0 else 0,
                    2
                )
            }
            for endpoint, data in stats.items()
        }
        return scraper_stats
    except Exception as e:
        logger.error(f"Error getting scraper stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting scraper stats")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
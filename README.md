# HirePro - Job Scraping and API Platform

HirePro is a robust job scraping and API platform that aggregates job listings from talentd.in. It provides a comprehensive API for accessing job listings, including regular jobs, freshers jobs, and internships.

## Features

- **Automated Job Scraping**
  - Scrapes jobs from multiple categories (Regular, Freshers, Internships)
  - Robust error handling and retry mechanisms
  - Progress tracking and state management
  - Automatic recovery from failures
  - System resource monitoring

- **RESTful API**
  - FastAPI-based REST API
  - Rate limiting and request tracking
  - Comprehensive job search and filtering
  - Detailed scraping status endpoints
  - Health monitoring endpoints

- **Advanced Features**
  - Real-time progress tracking
  - Detailed statistics and metrics
  - Request tracking and monitoring
  - IP-based analytics
  - Scraper detection

## Prerequisites

- Python 3.8+
- PostgreSQL database
- GeoLite2 database for IP geolocation

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/hirepro.git
cd hirepro
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
Create a `.env` file with the following variables:
```
DATABASE_URL=postgresql://user:password@localhost:5432/hirepro
GEOIP_DATABASE_PATH=/path/to/GeoLite2-City.mmdb
```

5. Download GeoLite2 database:
Download the GeoLite2 City database from MaxMind and place it in your project directory.

## Usage

### Starting the API Server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

### API Endpoints

#### Job Endpoints
- `GET /api/regular-jobs` - Get regular jobs
- `GET /api/freshers-jobs` - Get freshers jobs
- `GET /api/internships` - Get internship jobs
- `GET /api/jobs/{job_id}` - Get specific job details

#### Scraping Endpoints
- `GET /api/scrape` - Trigger job scraping
- `GET /api/scrape/status` - Get scraping status
- `GET /api/scrape/detailed-status` - Get detailed scraping status
- `POST /api/scrape/stop` - Stop scraping process

#### Monitoring Endpoints
- `GET /api/health` - Health check
- `GET /api/stats/active-users` - Get active users
- `GET /api/stats/endpoints` - Get endpoint statistics
- `GET /api/stats/ip/{ip}` - Get IP statistics
- `GET /api/stats/scraper` - Get scraper statistics

### Example API Usage

```python
import requests

# Get regular jobs
response = requests.get("http://localhost:8000/api/regular-jobs")
jobs = response.json()

# Search jobs
response = requests.get("http://localhost:8000/api/regular-jobs?search=python&location=bangalore")
filtered_jobs = response.json()

# Get scraping status
response = requests.get("http://localhost:8000/api/scrape/status")
status = response.json()
```

## Project Structure

```
hirepro/
├── api.py              # FastAPI application
├── scraper.py          # Job scraping logic
├── models.py           # Database models
├── config.py           # Configuration
├── request_tracker.py  # Request tracking
├── requirements.txt    # Dependencies
└── README.md          # Documentation
```

## Error Handling

The platform includes comprehensive error handling:
- Automatic retries for failed requests
- State recovery mechanisms
- Detailed error logging
- Graceful degradation

## Monitoring

The platform provides detailed monitoring capabilities:
- Real-time scraping progress
- System resource usage
- Request statistics
- Error tracking
- Performance metrics

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- FastAPI for the web framework
- SQLAlchemy for database ORM
- BeautifulSoup for web scraping
- MaxMind for GeoLite2 database 
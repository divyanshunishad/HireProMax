from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import threading
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import ipaddress
import geoip2.database
import logging

logger = logging.getLogger(__name__)

@dataclass
class RequestLog:
    timestamp: datetime
    endpoint: str
    method: str
    ip_address: str
    user_agent: str
    status_code: int
    response_time: float
    country: Optional[str] = None
    city: Optional[str] = None
    is_scraper: bool = False

class RequestTracker:
    def __init__(self, log_file: str = "request_logs.json", geoip_db: str = "GeoLite2-City.mmdb"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._active_requests: Dict[str, List[RequestLog]] = defaultdict(list)
        self._request_logs: List[RequestLog] = []
        self._load_logs()
        
        # Initialize GeoIP database
        try:
            self.geoip_reader = geoip2.database.Reader(geoip_db)
        except Exception as e:
            logger.warning(f"Could not load GeoIP database: {e}")
            self.geoip_reader = None

    def _load_logs(self):
        """Load existing logs from file"""
        try:
            if self.log_file.exists():
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    self._request_logs = [
                        RequestLog(
                            timestamp=datetime.fromisoformat(log['timestamp']),
                            endpoint=log['endpoint'],
                            method=log['method'],
                            ip_address=log['ip_address'],
                            user_agent=log['user_agent'],
                            status_code=log['status_code'],
                            response_time=log['response_time'],
                            country=log.get('country'),
                            city=log.get('city'),
                            is_scraper=log.get('is_scraper', False)
                        )
                        for log in data
                    ]
        except Exception as e:
            logger.error(f"Error loading request logs: {e}")
            self._request_logs = []

    def _save_logs(self):
        """Save logs to file"""
        try:
            with open(self.log_file, 'w') as f:
                json.dump(
                    [asdict(log) for log in self._request_logs],
                    f,
                    default=str
                )
        except Exception as e:
            logger.error(f"Error saving request logs: {e}")

    def _get_location_info(self, ip: str) -> tuple[Optional[str], Optional[str]]:
        """Get location information for an IP address"""
        try:
            if self.geoip_reader and not ipaddress.ip_address(ip).is_private:
                response = self.geoip_reader.city(ip)
                return response.country.name, response.city.name
        except Exception as e:
            logger.warning(f"Error getting location for IP {ip}: {e}")
        return None, None

    def _is_scraper(self, user_agent: str) -> bool:
        """Check if the request is from a scraper/bot"""
        scraper_indicators = [
            'bot', 'spider', 'crawler', 'scraper', 'python-requests',
            'curl', 'wget', 'postman', 'insomnia'
        ]
        user_agent_lower = user_agent.lower()
        return any(indicator in user_agent_lower for indicator in scraper_indicators)

    def log_request(self, endpoint: str, method: str, ip: str, user_agent: str,
                   status_code: int, response_time: float):
        """Log a new request"""
        with self._lock:
            country, city = self._get_location_info(ip)
            is_scraper = self._is_scraper(user_agent)
            
            log = RequestLog(
                timestamp=datetime.utcnow(),
                endpoint=endpoint,
                method=method,
                ip_address=ip,
                user_agent=user_agent,
                status_code=status_code,
                response_time=response_time,
                country=country,
                city=city,
                is_scraper=is_scraper
            )
            
            self._request_logs.append(log)
            self._active_requests[ip].append(log)
            
            # Keep only last 1000 logs
            if len(self._request_logs) > 1000:
                self._request_logs = self._request_logs[-1000:]
            
            # Save logs periodically
            if len(self._request_logs) % 10 == 0:
                self._save_logs()

    def get_active_users(self, time_window: int = 300) -> Dict:
        """Get active users in the last time_window seconds"""
        with self._lock:
            now = datetime.utcnow()
            active_users = defaultdict(lambda: {
                'count': 0,
                'endpoints': set(),
                'last_seen': None,
                'is_scraper': False
            })
            
            for log in self._request_logs:
                if (now - log.timestamp).total_seconds() <= time_window:
                    active_users[log.ip_address]['count'] += 1
                    active_users[log.ip_address]['endpoints'].add(log.endpoint)
                    active_users[log.ip_address]['last_seen'] = log.timestamp
                    active_users[log.ip_address]['is_scraper'] = log.is_scraper
            
            return {
                ip: {
                    'request_count': data['count'],
                    'endpoints': list(data['endpoints']),
                    'last_seen': data['last_seen'],
                    'is_scraper': data['is_scraper']
                }
                for ip, data in active_users.items()
            }

    def get_endpoint_stats(self, time_window: int = 3600) -> Dict:
        """Get statistics for each endpoint"""
        with self._lock:
            now = datetime.utcnow()
            stats = defaultdict(lambda: {
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'avg_response_time': 0,
                'unique_ips': set(),
                'scraper_requests': 0
            })
            
            for log in self._request_logs:
                if (now - log.timestamp).total_seconds() <= time_window:
                    stats[log.endpoint]['total_requests'] += 1
                    stats[log.endpoint]['unique_ips'].add(log.ip_address)
                    if 200 <= log.status_code < 400:
                        stats[log.endpoint]['successful_requests'] += 1
                    else:
                        stats[log.endpoint]['failed_requests'] += 1
                    if log.is_scraper:
                        stats[log.endpoint]['scraper_requests'] += 1
                    
                    # Update average response time
                    current_avg = stats[log.endpoint]['avg_response_time']
                    count = stats[log.endpoint]['total_requests']
                    stats[log.endpoint]['avg_response_time'] = (
                        (current_avg * (count - 1) + log.response_time) / count
                    )
            
            return {
                endpoint: {
                    'total_requests': data['total_requests'],
                    'successful_requests': data['successful_requests'],
                    'failed_requests': data['failed_requests'],
                    'avg_response_time': round(data['avg_response_time'], 3),
                    'unique_ips': len(data['unique_ips']),
                    'scraper_requests': data['scraper_requests']
                }
                for endpoint, data in stats.items()
            }

    def get_ip_stats(self, ip: str, time_window: int = 3600) -> Dict:
        """Get statistics for a specific IP address"""
        with self._lock:
            now = datetime.utcnow()
            stats = {
                'total_requests': 0,
                'endpoints': set(),
                'last_seen': None,
                'is_scraper': False,
                'countries': set(),
                'cities': set()
            }
            
            for log in self._request_logs:
                if log.ip_address == ip and (now - log.timestamp).total_seconds() <= time_window:
                    stats['total_requests'] += 1
                    stats['endpoints'].add(log.endpoint)
                    stats['last_seen'] = log.timestamp
                    stats['is_scraper'] = log.is_scraper
                    if log.country:
                        stats['countries'].add(log.country)
                    if log.city:
                        stats['cities'].add(log.city)
            
            return {
                'total_requests': stats['total_requests'],
                'endpoints': list(stats['endpoints']),
                'last_seen': stats['last_seen'],
                'is_scraper': stats['is_scraper'],
                'countries': list(stats['countries']),
                'cities': list(stats['cities'])
            }

    def cleanup_old_logs(self, max_age_days: int = 7):
        """Clean up logs older than max_age_days"""
        with self._lock:
            cutoff = datetime.utcnow() - timedelta(days=max_age_days)
            self._request_logs = [log for log in self._request_logs if log.timestamp > cutoff]
            self._save_logs()

# Create a global instance
request_tracker = RequestTracker() 
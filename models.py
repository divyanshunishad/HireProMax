from sqlalchemy import Column, Integer, String, DateTime, CheckConstraint
from sqlalchemy.exc import SQLAlchemyError
from config import Base
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class BaseJob:
    """Base class for common job fields"""
    id = Column(Integer, primary_key=True, index=True)
    job_title = Column(String(255), nullable=False)
    company_location = Column(String(255), nullable=False)
    salary = Column(String(100), nullable=True)
    job_type = Column(String(100), nullable=True)
    posted = Column(String(100), nullable=True)
    skills = Column(String(1000), nullable=True)
    eligible_years = Column(String(100), nullable=True)
    apply_url = Column(String(1000), nullable=False)
    company_logo = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id}, title='{self.job_title}')>"

    @classmethod
    def create(cls, db, **kwargs):
        try:
            job = cls(**kwargs)
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        except SQLAlchemyError as e:
            logger.error(f"Error creating job: {str(e)}")
            db.rollback()
            raise

class RegularJob(Base, BaseJob):
    """Model for regular jobs"""
    __tablename__ = "regular_jobs"

    __table_args__ = (
        CheckConstraint(
            "LENGTH(job_title) > 0",
            name="regular_non_empty_job_title"
        ),
        CheckConstraint(
            "LENGTH(company_location) > 0",
            name="regular_non_empty_company_location"
        ),
        CheckConstraint(
            "LENGTH(apply_url) > 0",
            name="regular_non_empty_apply_url"
        ),
    )

class FreshersJob(Base, BaseJob):
    """Model for freshers jobs"""
    __tablename__ = "freshers_jobs"

    __table_args__ = (
        CheckConstraint(
            "LENGTH(job_title) > 0",
            name="freshers_non_empty_job_title"
        ),
        CheckConstraint(
            "LENGTH(company_location) > 0",
            name="freshers_non_empty_company_location"
        ),
        CheckConstraint(
            "LENGTH(apply_url) > 0",
            name="freshers_non_empty_apply_url"
        ),
    )

class InternshipJob(Base, BaseJob):
    """Model for internship jobs"""
    __tablename__ = "internship_jobs"

    __table_args__ = (
        CheckConstraint(
            "LENGTH(job_title) > 0",
            name="internship_non_empty_job_title"
        ),
        CheckConstraint(
            "LENGTH(company_location) > 0",
            name="internship_non_empty_company_location"
        ),
        CheckConstraint(
            "LENGTH(apply_url) > 0",
            name="internship_non_empty_apply_url"
        ),
    ) 
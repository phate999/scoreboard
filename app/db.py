from typing import AsyncGenerator

import uuid
from fastapi import Depends
from fastapi_users.models import ID
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UUID, JSON, DateTime
from datetime import datetime, UTC

from pydantic import BaseModel, Json

DATABASE_URL = "sqlite+aiosqlite:///./test.db"


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    application_assignments = relationship("ApplicationAssignment", back_populates="user")
    submissions = relationship("Submission", back_populates="user")
    attachments = relationship("Attachment", back_populates="user")

class Applications(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    description = Column(String, nullable=True)
    instructions = Column(String, nullable=True)

    application_assignments = relationship("ApplicationAssignment", back_populates="applications")
    submissions = relationship("Submission", back_populates="applications")

class ApplicationCreate(BaseModel):
    name: str
    is_active: bool
    description: str
    instructions: str
    
class ApplicationAssignment(Base):
    __tablename__ = "application_assignments"

    user_id = Column(UUID, ForeignKey("user.id"), primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), primary_key=True)
    is_admin = Column(Boolean, default=False)

    user = relationship("User", back_populates="application_assignments")
    applications = relationship("Applications", back_populates="application_assignments")

class ApplicationAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    application_id: int
    is_admin: bool

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    user_id = Column(UUID, ForeignKey("user.id"))
    submission = Column(String, nullable=True)
    attachments = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="submissions")
    applications = relationship("Applications", back_populates="submissions")

class SubmissionCreate(BaseModel):
    application_id: int
    submission: str
    attachments: Json

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(UUID, primary_key=True, index=True)
    mime_type = Column(String, nullable=False)
    user_id = Column(UUID, ForeignKey("user.id"))
    desc = Column(String, nullable=False)

    user = relationship("User", back_populates="attachments")


engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User) 
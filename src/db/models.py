import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Feed(Base):
    __tablename__ = "feeds"

    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String, default="")
    site_url = Column(String, default="")
    category = Column(String, default="")
    enabled = Column(Boolean, default=True)
    last_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    articles = relationship("Article", back_populates="feed", cascade="all, delete-orphan")


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False)
    url = Column(String, unique=True, nullable=False)
    title = Column(String, default="")
    author = Column(String, default="")
    summary = Column(Text, default="")
    content = Column(Text, default="")
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)

    feed = relationship("Feed", back_populates="articles")
    score = relationship("Score", back_populates="article", uselist=False, cascade="all, delete-orphan")
    feedback_list = relationship("Feedback", back_populates="article", cascade="all, delete-orphan")


class Score(Base):
    __tablename__ = "scores"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), unique=True, nullable=False)
    relevance = Column(Float, default=0.0)
    significance = Column(Float, default=0.0)
    summary = Column(Text, default="")
    topics = Column(Text, default="[]")  # JSON array
    reason = Column(Text, default="")
    scored_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    article = relationship("Article", back_populates="score")

    @property
    def topics_list(self) -> list[str]:
        return json.loads(self.topics) if self.topics else []

    @topics_list.setter
    def topics_list(self, value: list[str]):
        self.topics = json.dumps(value)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    action = Column(String, nullable=False)  # like, dislike, save, skip
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    article = relationship("Article", back_populates="feedback_list")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, default="{}")  # JSON
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

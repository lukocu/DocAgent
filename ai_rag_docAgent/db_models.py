from datetime import datetime
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB 
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass
class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    uuid: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    source_uuid: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    text: Mapped[str] = mapped_column(Text, nullable=False)
    

    metadata_col: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<DocumentModel(id={self.id}, uuid='{self.uuid}')>"
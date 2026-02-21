from typing import Optional, List, Dict
from pydantic import BaseModel

class DocMetadata(BaseModel):
    """Metadata for a document or chunk (tokens, source, MIME type, IDs, etc.)."""
    tokens: int
    source: Optional[str] = None
    mimeType: Optional[str] = None
    name: Optional[str] = None
    source_uuid: Optional[str] = None
    conversation_uuid: Optional[str] = None 
    uuid: Optional[str] = None
    duration: Optional[float] = None
    headers: Optional[Dict[str, List[str]]] = None
    urls: Optional[List[str]] = None
    images: Optional[List[str]] = None
    screenshots: Optional[List[str]] = None
    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None

class Doc(BaseModel):
    """Document with text content and its isolated metadata."""
    text: str    
    metadata: DocMetadata 
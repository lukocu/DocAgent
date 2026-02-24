import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from config import settings
import asyncio

from openai_service import OpenAIService

class VectorService:
    def __init__(self, openai_service: OpenAIService):
        self.openai_service = openai_service
        self.client = AsyncQdrantClient(url=settings.qdrant_url)

    async def ensure_collection(self, collection_name: str):
        if not await self.client.collection_exists(collection_name):
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=3072, distance=Distance.COSINE) 
            )
            
    async def add_points(self, collection_name: str, points: List[Dict[str, Any]]):
        await self.ensure_collection(collection_name)
        
        tasks = [self.openai_service.create_embedding(p["text"]) for p in points]
        embeddings = await asyncio.gather(*tasks)
        
        qdrant_points = []
        for i, vector in enumerate(embeddings):
            if not vector:
                continue
            
            p = points[i]
            point_id = p.get("uuid") or p.get("id") or str(uuid.uuid4())
            payload = {"text": p["text"], **p.get("metadata", {})}
            
            qdrant_points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        if qdrant_points:
            await self.client.upsert(collection_name=collection_name, points=qdrant_points)

    async def delete_point(self, collection_name: str, point_id: str):
        await self.client.delete(collection_name=collection_name, points_selector=[point_id])

    async def perform_search(self, collection_name: str, query: str, limit: int = 15, query_filter=None) -> List[Dict[str, Any]]:
        try:    
            vector = await self.openai_service.create_embedding(query)
            
            if not vector:
                return []
                
            response  = await self.client.query_points(
                collection_name=collection_name,
                query=vector,        
                limit=limit,
                with_payload=True,
                query_filter=query_filter
            )

            formatted_results = [
                {
                    "uuid": r.id,           
                    "score": r.score,       
                    **(r.payload or {})     
                }
                for r in response.points
            ]

            return formatted_results

        except Exception as e:
            print(f"Błąd podczas wyszukiwania w Qdrant: {e}")
            return []
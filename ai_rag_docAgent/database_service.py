import uuid
import asyncio
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from config import settings
from models import Doc, DocMetadata
from db_models import Base, DocumentModel
from search_service import SearchService
from vector_service import VectorService


class DatabaseService:
    def __init__(self, search_service: SearchService, vector_service: VectorService):
        self.search_service = search_service
        self.vector_service = vector_service
        
        self.engine = create_async_engine(settings.postgres_url, echo=False)
        

        self.async_session = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def initialize_database(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


    async def insert_document(self, document: Doc, for_search: bool = False):
            dict_meta = document.metadata.model_dump()
            doc_uuid = dict_meta.get("uuid", str(uuid.uuid4()))
            source_uuid = dict_meta.get("source_uuid", "unknown_source")
            
            async with self.async_session() as session:
                new_record = DocumentModel(
                    uuid=doc_uuid, 
                    source_uuid=source_uuid, 
                    text=document.text, 
                    metadata_col=dict_meta
                )
                session.add(new_record)
                await session.commit()
        
            if for_search:
                record = {"uuid": doc_uuid, "text": document.text, **dict_meta}
                await self.search_service.save_object("documents", record)
                await self.vector_service.add_points("documents", [{"id": doc_uuid, "text": document.text, "metadata": dict_meta}])


    async def get_document_by_uuid(self, doc_uuid: str) -> Optional[Dict[str, Any]]:
        async with self.async_session() as session:
            stmt = select(DocumentModel).where(DocumentModel.uuid == doc_uuid)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            if (doc):
                return {"uuid": doc.uuid, "text": doc.text, "metadata": doc.metadata_col}
        return None


    async def hybrid_search(self, query_vector: str, query_text: str, source_uuids: List[str] = None, limit: int = 15) -> List[Doc]:
        qdrant_filter = None
        if source_uuids:
            from qdrant_client.models import Filter, FieldCondition, MatchAny
            qdrant_filter = Filter(
                must=[FieldCondition(
                    key="source_uuid",
                    match=MatchAny(any=source_uuids)
                )]
            )

        meili_filter = None
        if source_uuids:
            uuids_str = ", ".join(f'"{uid}"' for uid in source_uuids)
            meili_filter = f"source_uuid IN [{uuids_str}]"

        vector_task = self.vector_service.perform_search(
            "documents", query_vector,
            limit=limit,
            query_filter=qdrant_filter
        )
        text_task = self.search_service.search_single_index(
            "documents", query_text,
            limit=limit,
            filters=meili_filter
        )

        vector_results, text_results = await asyncio.gather(vector_task, text_task)
        rrf_results = self._calculate_rrf(vector_results, text_results)

        if not rrf_results:
            return []

        avg_score = sum(item["score"] for item in rrf_results) / len(rrf_results)
        
        valid_items = [item for item in rrf_results if item["score"] >= avg_score]
        return [Doc(text=item["text"], metadata=item) for item in valid_items]  

    def _calculate_rrf(self, vector_results: List[Dict[str, Any]], text_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result_map = {}

        for index, result in enumerate(vector_results):
            uuid_val = result.get("uuid")
            if not uuid_val: continue
            
            result_map[uuid_val] = {
                **result,
                "vector_rank": index + 1,
                "text_rank": float('inf') 
            }

        for index, result in enumerate(text_results):
            uuid_val = result.get("uuid")
            if not uuid_val: continue

            if uuid_val in result_map:
                result_map[uuid_val]["text_rank"] = index + 1
            else:
                result_map[uuid_val] = {
                    **result,
                    "vector_rank": float('inf'),
                    "text_rank": index + 1
                }

        final_results = []
        for item in result_map.values():
            v_rank = item["vector_rank"]
            t_rank = item["text_rank"]
            
            if(v_rank != float('inf')):
               v_score = 1 / (v_rank + 60)
            else:  
               v_score = 0

            if(t_rank != float('inf')):
               t_score = 1 / (t_rank + 60)
            else:  
               t_score = 0   
            item["score"] = v_score + t_score
            final_results.append(item)

        final_results.sort(key=lambda x: x["score"], reverse=True)
        return final_results
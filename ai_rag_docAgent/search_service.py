from typing import Dict, Any, List, Optional
from meilisearch_python_sdk import AsyncClient
from config import settings
import asyncio

class SearchService:
    def __init__(self):
        self.client = AsyncClient(
            url=settings.meili_url, 
            api_key=settings.meili_master_key.get_secret_value()
        )

    async def setup_index_ux(self, index_name: str):
        index = self.client.index(index_name)
        await index.update_searchable_attributes(["text", "metadata"])

        await index.update_typo_tolerance({
            "enabled": True,
            "minWordSizeForTypos": {
                "oneTypo": 3,
                "twoTypos": 7
            }
        })
        print(f"Zaktualizowano ustawienia UX dla indeksu: {index_name}")

    async def search_single_index(self, index_name: str, query: str, filters: Any = None, limit: int = 20) -> List[Dict[str, Any]]:
 
        search_options = {
            "limit": limit,
            "attributes_to_highlight": ["*"], 
            "highlight_pre_tag": "<em>",
            "highlight_post_tag": "</em>",
        }
        
        if filters:
            search_options["filter"] = filters

        results = await self.client.index(index_name).search(query, **search_options)
        
        cleaned_hits = []
        for hit in results.hits:
            hit.pop("_formatted", None) 
            cleaned_hits.append(hit)
            
        return cleaned_hits

    
    async def save_object(self, index_name: str, record: Dict[str, Any]):
        if "uuid" not in record and "objectID" in record:
             record["uuid"] = record["objectID"]
        await self.client.index(index_name).add_documents([record], primary_key="uuid")

    async def save_objects(self, index_name: str, objects: List[Dict[str, Any]]):
        for obj in objects:
            if "uuid" not in obj and "objectID" in obj:
                obj["uuid"] = obj["objectID"]
        await self.client.index(index_name).add_documents(objects, primary_key="uuid")

    async def get_object(self, index_name: str, object_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.client.index(index_name).get_document(object_id)
        except Exception:
            return None

    async def partial_update_object(self, index_name: str, object_id: str, updates: Dict[str, Any]):
        updates_with_id = {"uuid": object_id, **updates}
        await self.client.index(index_name).update_documents([updates_with_id], primary_key="uuid")

    async def delete_object(self, index_name: str, object_id: str):
        await self.client.index(index_name).delete_document(object_id)

    async def clear_objects(self, index_name: str):
        await self.client.index(index_name).delete_all_documents()

    async def get_objects(self, index_name: str, object_ids: List[str]) -> List[Dict[str, Any]]:
        tasks = [self.get_object(index_name, obj_id) for obj_id in object_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if isinstance(res, dict)]
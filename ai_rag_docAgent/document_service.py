import asyncio
import aiofiles
import json
from typing import List, Optional, Dict, Any

from models import Doc
from openai_service import OpenAIService
from database_service import DatabaseService
from text_service import TextService
from utils import get_result


from prompts.answer import get_answer_prompt
from prompts.queries import get_analyzer_prompt
from prompts.synthesize import get_synthesize_prompt
from prompts.compress import get_compression_prompt
from prompts.extract import get_extract_prompt
from prompts.translate import get_translation_prompt

class DocumentService:
    def __init__(self, openai_service: OpenAIService, database_service: DatabaseService, text_service: TextService):
        self.openai_service = openai_service
        self.database_service = database_service
        self.text_service = text_service

    async def _ensure_directory_exists(self, file_path: str) -> None:
        from pathlib import Path
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)


    async def answer(self, query: str, documents: List[Doc]) -> str:
        if not documents:
            return "Brak dokumentów do analizy."

        analyzer_res = await self.openai_service.completion(
            messages=[{"role": "system", "content": get_analyzer_prompt()}, {"role": "user", "content": query}],
            json_mode=True
        )
        
        queries_data = json.loads(analyzer_res or '{"queries": []}')
        queries = queries_data.get("queries", [])
        source_uuids = list({doc.metadata.source_uuid for doc in documents if doc.metadata.source_uuid})

        search_tasks = [
            self.database_service.hybrid_search(q['natural'], q['search'], source_uuids)
            for q in queries
        ]
        search_results = await asyncio.gather(*search_tasks)

        unique_results = {res.metadata.uuid: res for results in search_results for res in results}.values()

        context_parts = []
        for doc in unique_results:
            restored = self.text_service.restore_placeholders(doc)
            context_parts.append(f'<doc uuid="{restored.metadata.uuid}">{restored.text}</doc>')
        
        context = "\n".join(context_parts)

        final_res = await self.openai_service.completion(
            messages=[
                {"role": "system", "content": get_answer_prompt(context)},
                {"role": "user", "content": query}
            ]
        )
        
        return get_result(final_res, "final_answer") or final_res

    async def synthesize(self, query: str, documents: List[Doc]) -> str:
        current_answer = ""
        
        for doc in documents:
            restored_doc = self.text_service.restore_placeholders(doc)
            
            res = await self.openai_service.completion(
                messages=[
                    {"role": "system", "content": get_synthesize_prompt(current_answer, query)},
                    {"role": "user", "content": f"New segment to integrate: {restored_doc.text}"}
                ]
            )
            current_answer = get_result(res, "final_answer") or current_answer

        return current_answer

    async def summarize(self, documents: List[Doc], general_context: str = "") -> str:
        async def process_doc(doc: Doc):
            res = await self.openai_service.completion(
                messages=[
                    {"role": "system", "content": get_compression_prompt(general_context)},
                    {"role": "user", "content": doc.text}
                ]
            )
            updated = doc.model_copy(update={"text": res})
            return self.text_service.restore_placeholders(updated).text

        tasks = [process_doc(d) for d in documents]
        results = await asyncio.gather(*tasks)
        
        merged = "\n\n".join(filter(None, results))
        
        path = "storage/results/summary.md"
        await self._ensure_directory_exists(path)
        async with aiofiles.open(path, mode='w', encoding='utf-8') as f:
            await f.write(merged)
            
        return merged

    async def translate(self, documents: List[Doc], source_lang: str, target_lang: str) -> List[Doc]:
        batch_size = 5
        results = []
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            async def translate_one(doc: Doc):
                user_msg = f"Translate the following text from {source_lang} to {target_lang}: {doc.text}"
                content = await self.openai_service.completion(
                    messages=[{"role": "system", "content": get_translation_prompt()}, {"role": "user", "content": user_msg}]
                )
                return doc.model_copy(update={"text": content})

            batch_results = await asyncio.gather(*[translate_one(d) for d in batch])
            results.extend(batch_results)
            
        return results
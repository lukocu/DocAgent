import tiktoken
import re
from typing import List, Tuple, Dict, Optional
from models import Doc, DocMetadata


class TextService:
    def __init__(self, model_name: str = "gpt-5"):
        self.model_name = model_name
        self.tokenizer = tiktoken.encoding_for_model(self.model_name)

    def count_tokens(self, text: str) -> int:
        tokens=self.tokenizer.encode(text)
        return len(tokens)

    def restore_placeholders(self, doc: Doc) -> Doc:
        restored_text = doc.text
        meta = doc.metadata

        if meta.images:
            for index, url in enumerate(meta.images):
                tag = f"({{{{$img{index}}}}})"
                restored_text = restored_text.replace(tag, f"({url})")

        if meta.urls:
            for index, url in enumerate(meta.urls):
                tag = f"({{{{$url{index}}}}})"
                restored_text = restored_text.replace(tag, f"({url})")

        return doc.model_copy(update={"text": restored_text})

    def extract_urls_and_images(self, text: str) -> Tuple[str, List[str], List[str]]:
        urls: List[str] = []
        images: List[str] = []

        def replace_image(match):
            alt_text = match.group(1)
            url = match.group(2)
            indeks = len(images)
            images.append(url)
            return f"![{alt_text}]({{{{$img{indeks}}}}})"
            
        def replace_url(match):
            link_text = match.group(1)
            url = match.group(2)
            if url.startswith("{{$img"):
                return match.group(0) 
            index = len(urls)
            urls.append(url)
  
            return f"[{link_text}]({{{{$url{index}}}}})"


        content = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, text)
        content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_url, content)

        return content, urls, images

    def extract_headers(self, text: str) -> Dict[str, List[str]]:
        headers: Dict[str, List[str]] ={}
        key: str

        for match in re.finditer(r"(^|\n)(#{1,6})\s+(.*)", text):
            level = len(match.group(2))
            header_text = match.group(3).strip()
            key = f'h{level}'
            headers.setdefault(key, []).append(header_text) 

        return headers 

    def split(self, text: str, limit: int, metadata: Optional[Dict] = None) -> List[Doc]:
        chunks = []
        position = 0
        current_headers = {}

        base_meta = metadata or {}

        while position < len(text):
            chunk_text, chunk_end = self._get_chunk(text, position, limit)
            tokens = self.count_tokens(chunk_text)

            extracted =self.extract_headers(chunk_text)
            self._update_current_headers(current_headers, extracted)
            content, urls, images = self.extract_urls_and_images(chunk_text)
            doc_metadata = DocMetadata(
                tokens=tokens,
                headers=current_headers.copy(),
                urls=urls,
                images=images,
                **base_meta
            )           
            chunks.append(Doc(text=content, metadata=doc_metadata))
            position = chunk_end

        return chunks

    def _get_chunk(self, text: str, start: int, limit: int) -> Tuple[str, int]:
        overhead = self.count_tokens("<|im_start|>user\n<|im_end|>\n<|im_start|>assistant<|im_end|>") - self.count_tokens("")
        
        tokens_total = self.count_tokens(text[start:])
        if tokens_total == 0:
            return "", len(text)
            
        ratio = len(text[start:]) / tokens_total
        estimated_end = int(start + (limit * ratio))
        end = min(estimated_end, len(text))
        
        chunk_text = text[start:end]
        tokens = self.count_tokens(chunk_text)
        
        while tokens + overhead > limit and end > start:
            end = end - max(1, int((end - start) * 0.1))
            chunk_text = text[start:end]
            tokens = self.count_tokens(chunk_text)

        end = self._adjust_chunk_end(text, start, end, limit, overhead)
        
        return text[start:end], end

    def _adjust_chunk_end(self, text: str, start: int, end: int, limit: int, overhead: int) -> int:
        min_chunk_tokens = limit * 0.8  

        next_newline = text.find('\n', end)
        prev_newline = text.rfind('\n', start, end)

        if next_newline != -1:
            extended_end = next_newline + 1
            if self.count_tokens(text[start:extended_end]) + overhead <= limit:
                return extended_end

        if prev_newline > start:
            reduced_end = prev_newline + 1
            tokens = self.count_tokens(text[start:reduced_end])
            if tokens >= min_chunk_tokens:
                return reduced_end

        return end


    def _update_current_headers(self, current: Dict[str, List[str]], extracted: Dict[str, List[str]]) -> None:
            for level in range (1,7):
                key = f"h{level}"
                if key in extracted:
                    current[key] = extracted[key]
                    self._clear_lower_headers(current, level)


    def _clear_lower_headers(self, headers: Dict[str, List[str]], level: int) -> None:
            for lower_level in range (level+1,7):
                 key = f"h{lower_level}"
                 headers.pop(key, None)

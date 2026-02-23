import base64
from typing import List, Dict, Optional
from openai import AsyncOpenAI
import aiofiles

class OpenAIService:
    def __init__(self):
        self.client = AsyncOpenAI()

    async def completion(self, messages: List[Dict[str,str]], model: str = "gpt-5-mini") -> Optional[str]:
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Błąd API OpenAI: {e}")
            return None            
    
    async def create_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = await self.client.embeddings.create(
                input=text, 
                model="text-embedding-3-large"
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Błąd API OpenAI: {e}")
            return None


    async def process_image(self, image_path: str) -> Optional[Dict[str, str]]:
        try:
            async with aiofiles.open(image_path, "rb") as image_file:
                content = await image_file.read()
                base64_image = base64.b64encode(content).decode("utf-8")

            response = await self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in detail."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                        ],
                    }
                ],
            )

            return {
                "description": response.choices[0].message.content,
                "image_path": image_path
            }

        except Exception as e:
            print(f"Błąd przetwarzania obrazu: {e}")
            return None

    async def transcribe(self, audio_path: str, language: str = "pl") -> Optional[str]:
        try:
            async with aiofiles.open(audio_path, "rb") as audio_file:
                audio_bytes = await audio_file.read()

            transcription = await self.client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",   
                file=("audio.wav", audio_bytes, "audio/wav"),  
                language=language
            )

            return transcription.text

        except Exception as e:
            print(f"Błąd API OpenAI (Whisper): {e}")
            return None  
import os
import asyncio
import httpx
import json
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from firecrawl import FirecrawlApp

from openai_service import OpenAIService
from prompts.websearch import select_resources_to_load_prompt

class WebSearchService:
    def __init__(self):
        self.openai_service = OpenAIService()

        self.allowed_domains = [
            {"name": "Wikipedia", "url": "wikipedia.org", "scrappable": True},
            {"name": "easycart", "url": "easycart.pl", "scrappable": True},
            {"name": "FS.blog", "url": "fs.blog", "scrappable": True},
            {"name": "arXiv", "url": "arxiv.org", "scrappable": True},
            {"name": "Instagram", "url": "instagram.com", "scrappable": False},
            {"name": "OpenAI", "url": "openai.com", "scrappable": True},
            {"name": "Brain overment", "url": "brain.overment.com", "scrappable": True},
            {"name": "Reuters", "url": "reuters.com", "scrappable": True},
            {"name": "MIT Technology Review", "url": "technologyreview.com", "scrappable": True},
            {"name": "Youtube", "url": "youtube.com", "scrappable": False},
            {"name": "Mrugalski / UWteam", "url": "mrugalski.pl", "scrappable": True},
            {"name": "Hacker News", "url": "news.ycombinator.com", "scrappable": True},
        ]
        
        self.api_key = os.getenv("FIRECRAWL_API_KEY", "")
        self.firecrawl_app = FirecrawlApp(api_key=self.api_key)


    async def search_web(self, queries: List[Dict[str, str]], conversation_uuid: str = "") -> List[Dict[str, Any]]:
        async def single_search(q: str, url: str):
            try:

                parsed_url = urlparse(url if url.startswith("http") else f"https://{url}")
                domain = parsed_url.netloc if parsed_url.netloc else parsed_url.path
                site_query = f"site:{domain} {q}"
                print(f"siteQuery: {site_query}")

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.firecrawl.dev/v0/search",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {self.api_key}"
                        },
                        json={
                            "query": site_query,
                            "searchOptions": {"limit": 6},
                            "pageOptions": {"fetchPageContent": False}
                        },
                        timeout=30.0
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"HTTP error! status: {response.status_code}")
                    
                    result = response.json()
                    
                    if result.get("success") and "data" in result:
                        return {
                            "query": q,
                            "domain": domain,
                            "results": [
                                {
                                    "url": item.get("url"),
                                    "title": item.get("title"),
                                    "description": item.get("description")
                                } for item in result["data"]
                            ]
                        }
                    else:
                        print(f"No results found for query: {site_query}")
                        return {"query": q, "domain": domain, "results": []}

            except Exception as e:
                print(f"Error searching for {q}: {e}")
                return {"query": q, "domain": url, "results": []}

        tasks = [single_search(item["q"], item["url"]) for item in queries]
        return await asyncio.gather(*tasks)

    async def select_resources_to_load(self, messages: List[Dict[str, str]], filtered_results: List[Dict[str, Any]]) -> List[str]:
        system_prompt = {
            "role": "system",
            "content": select_resources_to_load_prompt(filtered_results)
        }

        try:

            response_content = await self.openai_service.completion(
                messages=[system_prompt] + messages,
                model="gpt-4o"
            )

            if response_content:

                clean_json = response_content.replace("```json", "").replace("```", "").strip()
                result = json.loads(clean_json)
                selected_urls = result.get("urls", [])

                print(f"selectedUrls: {selected_urls}")

                valid_urls = [
                    url for url in selected_urls 
                    if any(url == item["url"] for res in filtered_results for item in res["results"])
                ]

                empty_domains = [r["domain"] for r in filtered_results if not r["results"]]
                
                return list(set(valid_urls + empty_domains))

            raise Exception("Unexpected response format or empty content")
        except Exception as e:
            print(f"Error selecting resources to load: {e}")
            return []


    async def scrape_urls(self, urls: List[str], conversation_uuid: str = "") -> List[Dict[str, str]]:
        print(f"Input (scrapeUrls): {urls}")


        def is_scrappable(url: str) -> bool:
            hostname = urlparse(url).netloc.replace("www.", "")
            allowed = next((d for d in self.allowed_domains if d["url"] == hostname), None)
            return allowed is not None and allowed["scrappable"]

        scrappable_urls = [url for url in urls if is_scrappable(url)]

        async def single_scrape(url: str):
            try:

                normalized_url = url.rstrip('/')

                scrape_result = await asyncio.to_thread(
                    self.firecrawl_app.scrape_url,
                    normalized_url,
                    {'formats': ['markdown']}
                )

                if scrape_result and scrape_result.get("markdown"):
                    return {"url": url, "content": scrape_result["markdown"].strip()}
                else:
                    print(f"No markdown content found for URL: {url}")
                    return {"url": url, "content": ""}
            except Exception as e:
                print(f"Error scraping URL {url}: {e}")
                return {"url": url, "content": ""}

        tasks = [single_scrape(url) for url in scrappable_urls]
        scraped_results = await asyncio.gather(*tasks)

        return [res for res in scraped_results if res and res["content"]]
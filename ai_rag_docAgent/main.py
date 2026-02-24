import asyncio
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from file_service import FileService
from openai_service import OpenAIService
from vector_service import VectorService
from search_service import SearchService
from database_service import DatabaseService
from document_service import DocumentService
from text_service import TextService

load_dotenv()
console = Console()

async def main():
    console.print(Panel("[bold cyan]Inicjalizacja Systemu[/bold cyan]"))

    openai_service  = OpenAIService()
    search_service  = SearchService()
    vector_service  = VectorService(openai_service)
    database_service = DatabaseService(search_service, vector_service)
    file_service    = FileService(chunk_size=4000)
    text_service    = TextService()
    document_service = DocumentService(openai_service, database_service, text_service)

    await database_service.initialize_database()
    await search_service.setup_index_ux("documents")

    # KROK 1: Przetwarzanie – FileService ogarnia UUID, chunking, metadane
    url = "https://cloud.overment.com/S04E03-1732688101.md"
    console.print(f"\n[yellow]📥 Pobieranie dokumentu:[/yellow] {url}")

    docs = await file_service.process(url, chunk_size=4000)
    console.print(f"[OK] Podzielono na [bold]{len(docs)}[/bold] fragmentów.")

    # KROK 2: Indeksowanie
    console.print("\n[yellow]⚙ Indeksowanie...[/yellow]")
    for doc in docs:
        await database_service.insert_document(doc, for_search=True)
    console.print("[OK] Indeksowanie zakończone.")

    # KROK 3: Pytanie AI
    query = "Czym jest i jak działa tokenizacja w modelach językowych?"
    console.print(f"\n[bold magenta]❓ Pytanie:[/bold magenta] {query}")

    answer = await document_service.answer(query, docs)
    console.print(Panel(answer, title="[bold white]Odpowiedź AI[/bold white]", border_style="green"))

    output_path = Path("storage/results/answer.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(answer, encoding="utf-8")
    console.print(f"\n[dim]💾 Zapisano do: {output_path}[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[red]Przerwano.[/red]")
    except Exception as e:
        import traceback
        console.print(f"\n[bold red]BŁĄD:[/bold red] {e}")
        console.print(traceback.format_exc())
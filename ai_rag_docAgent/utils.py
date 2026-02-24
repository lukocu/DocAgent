import re
from datetime import datetime
from typing import List, Any
from rich.console import Console
from rich.table import Table

console = Console()

def current_date_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def get_result(content: str, tag_name: str) -> str | None:
    if not content:
        return None
    

    pattern = f"<{tag_name}>(.*?)</{tag_name}>"
    match = re.search(pattern, content, re.DOTALL)
    
    return match.group(1).strip() if match else None

def display_results_as_table(results: List[Any]):
    table = Table(title="Evaluation Results")

    table.add_column("Query", style="cyan", no_wrap=False)
    table.add_column("Variables", style="magenta")
    table.add_column("Result", style="green")

    for res in results:
        status_color = "green" if res.get('success') else "red"
        
        table.add_row(
            str(res.get('query', '')),
            str(res.get('vars', '')),
            f"[{status_color}]{str(res.get('output', ''))}[/{status_color}]"
        )

    console.print(table)
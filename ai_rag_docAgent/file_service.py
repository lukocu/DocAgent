import uuid
import os
import re
import asyncio
import mimetypes
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from urllib.parse import urlparse

import httpx
import filetype
import markdownify

from models import Doc
from text_service import TextService
from audio_service import AudioService
from openai_service import OpenAIService

FileCategory = Literal["text", "audio", "image", "document"]


# ============================================================================
# KLASA FileService
# Główny serwis odpowiedzialny za pobieranie, zapisywanie i konwersję plików
# z różnych formatów (audio, tekst, dokumenty, obrazy) na ustrukturyzowany tekst.
# ============================================================================

class FileService:

    # -------------------------------------------------------------------------
    # KROK 0: Stałe i konfiguracja – odpowiednik readonly w TS
    # -------------------------------------------------------------------------

    TEMP_DIR = Path("storage/temp")

    # Zestawienie typów MIME dla plików biurowych
    OFFICE_MIME_TYPES: dict[str, str] = {
        "doc":   "application/msword",
        "docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls":   "application/vnd.ms-excel",
        "xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf":   "application/pdf",
        "googleDoc":   "application/vnd.google-apps.document",
        "googleSheet": "application/vnd.google-apps.spreadsheet",
    }

    # Kategoryzacja formatów – text / audio / image / document
    MIME_CATEGORIES: dict[str, dict] = {
        "text": {
            "extensions": [".txt", ".md", ".json", ".html", ".csv"],
            "mimes": [
                "text/plain", "text/markdown", "application/json",
                "text/html", "text/csv",
            ],
        },
        "audio": {
            "extensions": [".mp3", ".wav", ".ogg"],
            "mimes": ["audio/mpeg", "audio/wav", "audio/ogg"],
        },
        "image": {
            "extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
            "mimes": [
                "image/jpeg", "image/png", "image/gif",
                "image/bmp", "image/webp",
            ],
        },
        "document": {
            "extensions": [".pdf", ".doc", ".docx", ".xls", ".xlsx"],
            "mimes": [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ],
        },
    }

    DEFAULT_EXTENSIONS: dict[str, str] = {
        "audio":    "mp3",
        "text":     "txt",
        "image":    "jpg",
        "document": "bin",
    }

    # Google Drive scopes
    SCOPES = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents",
    ]

    # -------------------------------------------------------------------------
    # Konstruktor
    # -------------------------------------------------------------------------

    def __init__(self, chunk_size: int = 4000):
        self.text_service   = TextService(model_name="gpt-4o-mini")
        self.audio_service  = AudioService()
        self.openai_service = OpenAIService()
        self.chunk_size     = chunk_size
        self._auth_client   = None   # Lazy init przez _initialize_google_auth()

    # =========================================================================
    # GOOGLE DRIVE – inicjalizacja auth
    # Analogia do initializeGoogleAuth() w TS
    # =========================================================================

    async def _initialize_google_auth(self) -> None:
        """Inicjalizuje klienta Google Auth ze zmiennych środowiskowych."""
        try:
            import os
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            private_key = (os.getenv("GOOGLE_PRIVATE_KEY") or "").replace("\\n", "\n")

            credentials_info = {
                "type": "service_account",
                "project_id":                 os.getenv("GOOGLE_PROJECT_ID"),
                "private_key_id":             os.getenv("GOOGLE_PRIVATE_KEY_ID"),
                "private_key":                private_key,
                "client_email":               os.getenv("GOOGLE_CLIENT_EMAIL"),
                "client_id":                  os.getenv("GOOGLE_CLIENT_ID"),
                "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
                "token_uri":                  "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": (
                    f"https://www.googleapis.com/robot/v1/metadata/x509/"
                    f"{os.getenv('GOOGLE_CLIENT_EMAIL')}"
                ),
            }

            self._auth_client = service_account.Credentials.from_service_account_info(
                credentials_info, scopes=self.SCOPES
            )
        except Exception as e:
            print(f"Failed to initialize Google Auth: {e}")
            raise

    # =========================================================================
    # OPERACJE NA PLIKACH
    # =========================================================================

    async def write_temp_file(self, file_content: bytes, file_name: str) -> str:
        """
        Tworzy plik tymczasowy na dysku.
        Analogia do writeTempFile() w TS.
        """
        temp_uuid = str(uuid.uuid4())
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = self.TEMP_DIR / f"{file_name}-{temp_uuid}"

        try:
            temp_path.write_bytes(file_content)
            await self._check_mime_type(str(temp_path), "text")
            return str(temp_path)
        except Exception as e:
            print(f"Failed to write temp file: {e}")
            raise

    async def save(
        self,
        file_content: bytes,
        file_name: str,
        file_uuid: str,
        file_type: FileCategory,
        source: Optional[str] = None,
    ) -> dict:
        """
        Zapisuje plik w strukturze storage/{type}/{data}/{uuid}/nazwa.
        Analogia do save() w TS.
        """
        try:
            # Ścieżka oparta na dacie – jak w oryginale TS
            today     = datetime.now()
            date_path = today.strftime("%Y-%m-%d")
            dir_path  = Path("storage") / file_type / date_path / file_uuid
            dir_path.mkdir(parents=True, exist_ok=True)

            # Wykrywamy MIME z zawartości – nie ufamy nazwie pliku
            mime_type = self._get_mime_type_from_bytes(file_content, file_name)

            # Rozszerzenie: bierzemy z oryginalnej nazwy lub z MIME
            original_ext = Path(file_name).suffix.lstrip(".")
            if original_ext:
                file_ext = original_ext
            else:
                file_ext = (
                    mimetypes.guess_extension(mime_type, strict=False) or
                    self.DEFAULT_EXTENSIONS.get(file_type, "bin")
                ).lstrip(".")

            print(f"typ: {file_type}")

            # Walidacja – MIME musi pasować do zadeklarowanego typu
            if mime_type not in self.MIME_CATEGORIES[file_type]["mimes"]:
                raise ValueError(
                    f"MIME {mime_type} nie pasuje do oczekiwanego typu {file_type}"
                )

            # Budowanie nowej nazwy i zapis
            stem         = Path(file_name).stem
            new_name     = f"{stem}.{file_ext}"
            file_path    = dir_path / new_name
            file_path.write_bytes(file_content)

            result = {
                "type":     file_type,
                "path":     str(file_path),
                "fileName": new_name,
                "mimeType": mime_type,
                "fileUUID": file_uuid,
            }
            if source:
                result["source"] = source

            print(f"File saved to: {result}")
            return result

        except Exception as e:
            print(f"Failed to save file: {e}")
            raise

    # =========================================================================
    # ODCZYT PLIKÓW TEKSTOWYCH I DOKUMENTÓW
    # =========================================================================

    async def read_text_file(self, original_path: str, storage_path: str) -> Doc:
        """
        Wczytuje plik tekstowy i opakowuje w Doc.
        Analogia do readTextFile() w TS.
        """
        try:
            mime_type = self._get_mime_type_from_path(storage_path)

            if mime_type not in self.MIME_CATEGORIES["text"]["mimes"]:
                raise ValueError(f"Nieobsługiwany typ MIME: {mime_type}")

            text = Path(storage_path).read_text(encoding="utf-8")
            doc  = self.text_service.document(
                text,
                metadata={
                    "source":   original_path,
                    "path":     storage_path,
                    "name":     Path(original_path).name,
                    "mimeType": mime_type,
                },
            )
            return doc
        except Exception as e:
            print(f"Failed to read text file: {e}")
            raise

    async def read_document_file(self, original_path: str, storage_path: str) -> Doc:
        """
        Czyta plik Office lub PDF → ekstrahuje czysty tekst → Doc.
        Analogia do readDocumentFile() w TS.
        """
        try:
            mime_type = self._get_mime_type_from_path(storage_path)

            if mime_type not in self.MIME_CATEGORIES["document"]["mimes"]:
                raise ValueError(f"Nieobsługiwany MIME dokumentu: {mime_type}")

            office_mimes = [
                self.OFFICE_MIME_TYPES["doc"],
                self.OFFICE_MIME_TYPES["docx"],
                self.OFFICE_MIME_TYPES["xls"],
                self.OFFICE_MIME_TYPES["xlsx"],
            ]

            if mime_type in office_mimes:
                print(f"Processing office file... {mime_type}")
                result   = await self._process_office_file(storage_path)
                content  = result["markdown"]
            elif mime_type == self.OFFICE_MIME_TYPES["pdf"]:
                content = await self._read_pdf_file(storage_path)
            else:
                raise ValueError(f"Nieobsługiwany MIME: {mime_type}")

            doc = self.text_service.document(
                content.strip(),
                metadata={
                    "source":   original_path,
                    "path":     storage_path,
                    "name":     Path(original_path).name,
                    "mimeType": mime_type,
                },
            )
            return doc
        except Exception as e:
            print(f"Failed to read document file: {e}")
            raise

    # =========================================================================
    # MIME TYPE – wykrywanie
    # Analogia do getMimeType() / getMimeTypeFromBuffer() w TS
    # =========================================================================

    def _get_mime_type_from_bytes(self, file_bytes: bytes, file_name: str) -> str:
        """
        Wykrywa MIME z zawartości (nie z nazwy).
        Analogia do getMimeTypeFromBuffer() używającego file-type w TS.
        """
        # Priorytet 1: analiza bajtów przez filetype
        kind = filetype.guess(file_bytes)
        if kind:
            return kind.mime

        # Priorytet 2: rozszerzenie pliku
        mime, _ = mimetypes.guess_type(file_name)
        if mime:
            return mime

        return "application/octet-stream"

    def _get_mime_type_from_path(self, file_path: str) -> str:
        """Odczytuje MIME na podstawie ścieżki – wczytuje plik i analizuje bajty."""
        data = Path(file_path).read_bytes()
        return self._get_mime_type_from_bytes(data, file_path)

    async def _check_mime_type(
        self, file_path: str, expected_type: FileCategory
    ) -> None:
        """Sprawdza czy MIME pliku pasuje do oczekiwanej kategorii."""
        mime_type = self._get_mime_type_from_path(file_path)
        if mime_type not in self.MIME_CATEGORIES[expected_type]["mimes"]:
            raise ValueError(
                f"Nieobsługiwany MIME {mime_type} dla kategorii {expected_type}"
            )

    # =========================================================================
    # KONWERSJA PLIKÓW BIUROWYCH
    # Analogia do processOfficeFile() w TS
    # =========================================================================

    async def _process_office_file(self, file_path: str) -> dict:
        """
        Wysyła plik Office na Google Drive, konwertuje i pobiera jako HTML/CSV.
        Zwraca { markdown, pdf_path }.
        """
        p        = Path(file_path)
        ext      = p.suffix.lstrip(".")
        mime     = self.OFFICE_MIME_TYPES.get(ext)
        if not mime:
            raise ValueError(f"Nieobsługiwany typ pliku: {ext}")

        temp_files: list[Path] = []

        try:
            file_id   = await self._upload_file_to_drive(file_path, mime)
            base_name = p.stem

            self.TEMP_DIR.mkdir(parents=True, exist_ok=True)

            # HTML dla Worda, CSV dla Excela
            inter_ext  = "csv" if "xl" in ext else "html"
            inter_path = self.TEMP_DIR / f"{base_name}.{inter_ext}"
            pdf_path   = self.TEMP_DIR / f"{base_name}.pdf"
            temp_files.append(inter_path)

            await self._get_plain_file_contents_from_drive(file_id, str(inter_path), mime)
            await self._download_as_pdf(file_id, str(pdf_path), mime)

            if "xl" in ext:
                csv_content = inter_path.read_text(encoding="utf-8")
                markdown    = self._csv_to_markdown(csv_content)
            else:
                markdown = self._convert_html_to_markdown(str(inter_path))

            return {"markdown": markdown, "pdf_path": str(pdf_path)}

        except Exception as e:
            print(f"Failed to process Office file: {e}")
            raise
        finally:
            for tf in temp_files:
                tf.unlink(missing_ok=True)

    def _csv_to_markdown(self, csv_content: str) -> str:
        """Zamienia CSV na tabelę Markdown. Analogia do csvToMarkdown() w TS."""
        lines  = csv_content.strip().split("\n")
        if not lines:
            return ""

        headers = lines[0].split(",")
        rows    = lines[1:]

        md_lines = [
            f"| {' | '.join(headers)} |",
            f"| {' | '.join(['---'] * len(headers))} |",
        ]
        for row in rows:
            md_lines.append(f"| {' | '.join(row.split(','))} |")

        return "\n".join(md_lines)

    def _convert_html_to_markdown(self, file_path: str) -> str:
        """
        HTML → Markdown za pomocą markdownify.
        Analogia do convertHTMLToMarkdown() używającego Turndown w TS.
        """
        try:
            html = Path(file_path).read_text(encoding="utf-8")
            return markdownify.markdownify(html, heading_style="ATX")
        except Exception as e:
            print(f"Failed to convert HTML to Markdown: {e}")
            raise

    # =========================================================================
    # NARZĘDZIA ZEWNĘTRZNE
    # =========================================================================

    async def _check_external_tool(self, tool_name: str) -> None:
        """Sprawdza czy narzędzie CLI jest dostępne w PATH."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "where" if os.name == "nt" else "which",
                tool_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"{tool_name} nie jest zainstalowany lub nie ma go w PATH")
        except Exception:
            raise RuntimeError(f"{tool_name} nie jest zainstalowany lub nie ma go w PATH")

    # =========================================================================
    # PDF
    # Analogia do readPdfFile() w TS
    # =========================================================================

    async def _read_pdf_file(self, file_path: str) -> str:
        """
        Konwertuje PDF → HTML (pdftohtml) → Markdown.
        Analogia do readPdfFile() w TS.
        """
        await self._check_external_tool("pdftohtml")

        temp_html = Path(f"{file_path}.html")

        try:
            proc = await asyncio.create_subprocess_exec(
                "pdftohtml", "-s", "-i", "-noframes",
                file_path, str(temp_html),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"pdftohtml error: {stderr.decode()}")

            html = temp_html.read_text(encoding="utf-8")

            # Wycinamy zbędne tagi – jak w TS
            html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
            html = re.sub(r"<title>.*?</title>", "", html, flags=re.IGNORECASE | re.DOTALL)

            return markdownify.markdownify(html, heading_style="ATX")

        except Exception as e:
            print(f"Failed to read PDF file: {e}")
            raise
        finally:
            temp_html.unlink(missing_ok=True)

    # =========================================================================
    # GOOGLE DRIVE – operacje
    # Analogia do uploadFileToDrive / convertToDriveFormat / getPlainFileContents...
    # =========================================================================

    async def _upload_file_to_drive(self, file_path: str, mime_type: str) -> str:
        """Wgrywa plik na Google Drive. Zwraca file_id."""
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            if not self._auth_client:
                await self._initialize_google_auth()

            service   = build("drive", "v3", credentials=self._auth_client)
            file_name = Path(file_path).name

            file_metadata = {"name": file_name}
            media = MediaFileUpload(file_path, mimetype=mime_type)

            result = service.files().create(
                body=file_metadata, media_body=media, fields="id"
            ).execute()

            file_id = result.get("id")
            if not file_id:
                raise RuntimeError("Google Drive nie zwróciło ID pliku")

            return file_id

        except Exception as e:
            print(f"Failed to upload file to Drive: {e}")
            raise

    async def _convert_to_drive_format(
        self, file_id: str, source_mime_type: str
    ) -> str:
        """Konwertuje plik w Drive do Google Docs/Sheets. Zwraca nowe ID."""
        try:
            from googleapiclient.discovery import build

            if not self._auth_client:
                await self._initialize_google_auth()

            service = build("drive", "v3", credentials=self._auth_client)
            target_mime = (
                self.OFFICE_MIME_TYPES["googleSheet"]
                if "sheet" in source_mime_type
                else self.OFFICE_MIME_TYPES["googleDoc"]
            )

            result = service.files().copy(
                fileId=file_id,
                body={"mimeType": target_mime}
            ).execute()

            new_id = result.get("id")
            if not new_id:
                raise RuntimeError("Nie udało się skonwertować pliku w Drive")
            return new_id

        except Exception as e:
            print(f"Failed to convert file in Drive: {e}")
            raise

    async def _get_plain_file_contents_from_drive(
        self, file_id: str, output_path: str, mime_type: str
    ) -> None:
        """Pobiera plik z Drive jako CSV lub HTML."""
        try:
            from googleapiclient.discovery import build

            if not self._auth_client:
                await self._initialize_google_auth()

            converted_id  = await self._convert_to_drive_format(file_id, mime_type)
            service       = build("drive", "v3", credentials=self._auth_client)
            is_sheet      = "sheet" in mime_type
            export_mime   = "text/csv" if is_sheet else "text/html"

            request  = service.files().export_media(
                fileId=converted_id, mimeType=export_mime
            )
            content  = request.execute()

            Path(output_path).write_bytes(content)
            await self._delete_drive_file(converted_id)

        except Exception as e:
            print(f"Failed to get file contents from Drive: {e}")
            raise

    async def _download_as_pdf(
        self, file_id: str, output_path: str, mime_type: str
    ) -> None:
        """Pobiera plik z Drive jako PDF."""
        try:
            from googleapiclient.discovery import build

            if not self._auth_client:
                await self._initialize_google_auth()

            converted_id = await self._convert_to_drive_format(file_id, mime_type)
            service      = build("drive", "v3", credentials=self._auth_client)

            request = service.files().export_media(
                fileId=converted_id, mimeType="application/pdf"
            )
            content = request.execute()

            Path(output_path).write_bytes(content)
            await self._delete_drive_file(converted_id)

        except Exception as e:
            print(f"Failed to download PDF from Drive: {e}")
            raise

    async def _delete_drive_file(self, file_id: str) -> None:
        """Usuwa plik z Google Drive."""
        try:
            from googleapiclient.discovery import build

            if not self._auth_client:
                await self._initialize_google_auth()

            service = build("drive", "v3", credentials=self._auth_client)
            service.files().delete(fileId=file_id).execute()

        except Exception as e:
            print(f"Failed to delete file from Drive: {e}")

    # =========================================================================
    # SCREENSHOTY – PDF/Office → JPG
    # Analogia do takeScreenshot() w TS (pdf2pic + sharp → pdf2image + Pillow)
    # =========================================================================

    async def take_screenshot(
        self, file_path: str, file_name: str
    ) -> list[str]:
        """
        Konwertuje strony PDF/Office na obrazy JPG.
        Analogia do takeScreenshot() używającego pdf2pic + sharp w TS.
        """
        try:
            from pdf2image import convert_from_path
            from PIL import Image

            ext             = Path(file_path).suffix.lower()
            output_base     = Path(file_name).stem
            shot_uuid       = str(uuid.uuid4())
            saved_paths:    list[str] = []

            # Ustal ścieżkę do PDF
            if ext in [".doc", ".docx", ".xls", ".xlsx"]:
                result   = await self._process_office_file(file_path)
                pdf_path = result["pdf_path"]
                is_temp_pdf = True
            elif ext == ".pdf":
                pdf_path    = file_path
                is_temp_pdf = False
            else:
                raise ValueError(f"Nieobsługiwany typ dla zrzutów ekranu: {ext}")

            self.TEMP_DIR.mkdir(parents=True, exist_ok=True)

            # Landscape dla arkuszy Excel
            dpi = 300
            if ext in [".xls", ".xlsx"]:
                page_size = (3508, 2480)
            else:
                page_size = (2480, 3508)

            # Konwersja PDF → lista obrazów PIL
            pages = convert_from_path(pdf_path, dpi=dpi)

            for i, page in enumerate(pages, start=1):
                temp_out = self.TEMP_DIR / f"{output_base}_{i}.jpg"

                # Resize z zachowaniem proporcji – jak sharp.fit.inside w TS
                page.thumbnail(page_size, Image.LANCZOS)
                page.save(str(temp_out), "JPEG", quality=90)

                # Odczytaj jako bytes i zapisz przez self.save()
                image_bytes = temp_out.read_bytes()
                saved = await self.save(
                    image_bytes,
                    f"{output_base}_{i}.jpg",
                    shot_uuid,
                    "image",
                )
                saved_paths.append(saved["path"])

                # Sprzątanie pliku tymczasowego
                temp_out.unlink(missing_ok=True)

            # Usuń tymczasowy PDF jeśli był wygenerowany z Office
            if is_temp_pdf:
                Path(pdf_path).unlink(missing_ok=True)

            return saved_paths

        except Exception as e:
            print(f"Failed to take screenshot: {e}")
            raise

    async def _get_page_count(self, pdf_path: str) -> int:
        """Pobiera liczbę stron PDF przez pdfinfo."""
        await self._check_external_tool("pdfinfo")
        proc = await asyncio.create_subprocess_exec(
            "pdfinfo", pdf_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
        raise RuntimeError("Nie udało się odczytać liczby stron PDF")

    # =========================================================================
    # POBIERANIE URL
    # Analogia do fetchAndSaveUrlFile() w TS
    # =========================================================================

    async def fetch_and_save_url_file(
        self, url: str, file_uuid: str
    ) -> dict:
        """
        Pobiera plik z URL lub scrapuje stronę www.
        Analogia do fetchAndSaveUrlFile() w TS.
        """
        try:
            parsed    = urlparse(url)
            file_name = parsed.path.rstrip("/").split("/")[-1] or ""
            file_name = file_name.split("?")[0]  # Usuwamy query params z nazwy
            file_ext  = Path(file_name).suffix.lower()

            # Brak rozszerzenia → strona WWW → scraper
            if not file_ext:
                scraped = await self._scrape_url(url)
                if not scraped:
                    raise RuntimeError("Nie udało się zebrać treści ze strony")

                file_name    = f"{parsed.hostname}_{file_uuid}.md"
                file_content = scraped.encode("utf-8")
                saved = await self.save(
                    file_content, file_name, file_uuid, "text", url
                )
                return {**saved, "mimeType": "text/markdown"}

            # Pobieranie binarnego pliku
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                file_content = response.content

            # Ustalamy MIME
            if file_ext in self.MIME_CATEGORIES["text"]["extensions"]:
                mime_type, _ = mimetypes.guess_type(file_name)
                mime_type = mime_type or "text/plain"
            else:
                content_type = response.headers.get("content-type", "")
                mime_type    = content_type.split(";")[0].strip() or "application/octet-stream"

            file_type = self.get_file_category_from_mime(mime_type)

            if not file_name:
                file_name = f"file_{file_uuid}{file_ext}"

            saved = await self.save(file_content, file_name, file_uuid, file_type, url)
            print(f"File fetched and saved: {saved['path']}")
            return {**saved, "mimeType": mime_type}

        except Exception as e:
            print(f"Failed to fetch and save URL file: {e}")
            raise

    async def _scrape_url(self, url: str) -> Optional[str]:
        """
        Prosty scraper HTML → Markdown.
        Analogia do webSearchService.scrapeUrls() w TS.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
            return markdownify.markdownify(response.text, heading_style="ATX")
        except Exception as e:
            print(f"Scraping failed for {url}: {e}")
            return None

    # =========================================================================
    # HELPER – kategoria z MIME
    # Analogia do getFileCategoryFromMimeType() w TS
    # =========================================================================

    def get_file_category_from_mime(self, mime_type: str) -> FileCategory:
        for category, info in self.MIME_CATEGORIES.items():
            if mime_type in info["mimes"]:
                return category  # type: ignore
        return "document"

    # =========================================================================
    # KROK 1A: METODA GŁÓWNA – PROCESS
    # Analogia do process() w FileService.ts
    # =========================================================================

    async def process(
        self,
        file_path_or_url: str,
        chunk_size: Optional[int] = None,
    ) -> list[Doc]:
        """
        Główna metoda serwisu.
        Przyjmuje URL lub ścieżkę lokalną, zwraca listę Doc gotową do indeksowania.
        """
        limit     = chunk_size or self.chunk_size
        file_uuid = str(uuid.uuid4())   # ← jeden source_uuid dla całego pliku

        # -----------------------------------------------------------------
        # KROK 2: Ustal źródło i zapisz plik lokalnie
        # -----------------------------------------------------------------
        if file_path_or_url.startswith("http://") or file_path_or_url.startswith("https://"):
            saved       = await self.fetch_and_save_url_file(file_path_or_url, file_uuid)
            original    = file_path_or_url
            storage     = saved["path"]
        else:
            original    = file_path_or_url
            file_bytes  = Path(original).read_bytes()
            mime_type   = self._get_mime_type_from_bytes(file_bytes, Path(original).name)
            ftype       = self.get_file_category_from_mime(mime_type)
            saved       = await self.save(
                file_bytes, Path(original).name, file_uuid, ftype, original
            )
            storage     = saved["path"]

        # -----------------------------------------------------------------
        # KROK 3: Ponowne wykrycie kategorii z zapisanego pliku
        # -----------------------------------------------------------------
        mime_type = self._get_mime_type_from_path(storage)
        ftype     = self.get_file_category_from_mime(mime_type)

        docs:            list[Doc] = []
        screenshot_paths: Optional[list[str]] = None

        # -----------------------------------------------------------------
        # KROK 4: Routing wg kategorii – analogia do switch(type) w TS
        # -----------------------------------------------------------------

        # ── AUDIO ──────────────────────────────────────────────────────
        if ftype == "audio":
            chunk_paths = await self.audio_service.split(storage, 25)

            for i, chunk_path in enumerate(chunk_paths):
                text = await self.openai_service.transcribe(chunk_path, language="pl")
                
                meta = {
                    "file_name":    Path(original).stem + ".md",
                    "chunk_index":  i,
                    "total_chunks": len(chunk_paths),
                    "source_uuid":  file_uuid,
                    "uuid":         str(uuid.uuid4()),
                }

                if limit:
                    sub_docs = self.text_service.split(text or "", limit=limit, metadata=meta)
                    for d in sub_docs:
                        d.metadata.uuid = str(uuid.uuid4())
                    docs.extend(sub_docs)
                else:
                    docs.append(self.text_service.document(text or "", metadata=meta))

            for cp in chunk_paths:
                Path(cp).unlink(missing_ok=True)

        
            for cp in chunk_paths:
                        Path(cp).unlink(missing_ok=True)

        # ── TEKST ──────────────────────────────────────────────────────
        elif ftype == "text":
            text_content = Path(storage).read_text(encoding="utf-8")
            base_meta    = {
                "source":      original,
                "path":        storage,
                "name":        Path(original).name,
                "mimeType":    mime_type,
                "source_uuid": file_uuid,
            }

            if limit:
                raw_docs = self.text_service.split(
                    text_content, limit=limit, metadata=base_meta
                )
                for doc in raw_docs:
                    doc.metadata.uuid = str(uuid.uuid4())   # ← uuid per chunk
                docs = raw_docs
            else:
                base_meta["uuid"] = str(uuid.uuid4())
                docs = [
                    self.text_service.document(text_content, metadata=base_meta)
                ]

        # ── DOKUMENT (PDF / Office) ─────────────────────────────────────
        elif ftype == "document":
            doc_content = await self.read_document_file(original, storage)

            if limit:
                docs = self.text_service.split(doc_content.text, limit=limit)
            else:
                docs = [doc_content]

            screenshot_paths = await self.take_screenshot(
                storage, Path(original).name
            )
            print(f"Screenshots saved to: {screenshot_paths}")

            # Przypisanie screenshotów do każdego chunku
            for i, doc in enumerate(docs):
                doc.metadata.source_uuid    = file_uuid
                doc.metadata.uuid           = str(uuid.uuid4())
                doc.metadata.screenshots    = screenshot_paths
                doc.metadata.chunk_index    = i
                doc.metadata.total_chunks   = len(docs)

        # ── OBRAZ ──────────────────────────────────────────────────────
        elif ftype == "image":
            result = await self.openai_service.process_image(storage)

            docs = [self.text_service.document(
                result["description"],
                metadata={
                    "source":      original,
                    "path":        storage,
                    "name":        Path(original).name,
                    "mimeType":    mime_type,
                    "source_uuid": file_uuid,
                    "uuid":        str(uuid.uuid4()),
                },
            )]

        else:
            raise ValueError(f"Nieobsługiwany typ pliku: {ftype}")

        # -----------------------------------------------------------------
        # KROK 5: Zwróć gotową listę Doc
        # -----------------------------------------------------------------
        return docs
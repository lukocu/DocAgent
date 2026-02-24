import asyncio
import os
import re
import json
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import subprocess



@dataclass
class AudioMetadata:
    duration: float
    sample_rate: int
    channels: int
    bit_rate: int
    codec: str
    format: str


@dataclass
class AudioLoudnessData:
    time: float
    loudness: float  


@dataclass
class SilenceInterval:
    start: float
    end: float
    duration: float


@dataclass
class AudioChunk:
    start: float
    end: float


@dataclass
class NonSilentInterval:
    start: float
    end: float
    duration: float




class AudioService:

    STORAGE_DIR = Path("storage/chunks")



    async def get_metadata(self, file_path: str) -> AudioMetadata:
        """Odczytuje metadane pliku audio przez ffprobe."""
        data = await self._probe_file(file_path)
        return self._extract_metadata(data)

    async def _probe_file(self, file_path: str) -> dict:
        """Uruchamia ffprobe i zwraca surowy JSON."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-of", "json",
            "-show_format",
            "-show_streams",
            file_path
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe error: {stderr.decode()}")

        return json.loads(stdout.decode())

    def _extract_metadata(self, data: dict) -> AudioMetadata:
        """Wyciąga potrzebne pola z surowego JSON ffprobe."""
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            None
        )
        if not audio_stream:
            raise ValueError("Brak strumienia audio w pliku")

        fmt = data.get("format", {})
        return AudioMetadata(
            duration=float(fmt.get("duration", 0)),
            sample_rate=int(audio_stream.get("sample_rate", 0)),
            channels=int(audio_stream.get("channels", 0)),
            bit_rate=int(audio_stream.get("bit_rate", 0)),
            codec=audio_stream.get("codec_name", "unknown"),
            format=fmt.get("format_name", "unknown"),
        )


    async def analyze_loudness(
        self, file_path: str, interval: float = 0.1
    ) -> list[AudioLoudnessData]:
        """Bada poziom głośności (RMS) w małych odstępach czasu."""
        loudness_data: list[AudioLoudnessData] = []

        cmd = [
            "ffmpeg", "-i", file_path,
            "-af", f"astats=metadata=1:reset={interval},aresample=8000",
            "-f", "null", "-"
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await result.communicate()
        stderr_text = stderr.decode()

        rms_pattern   = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?)")
        time_pattern  = re.compile(r"pts_time:(\d+(?:\.\d+)?)")

        for line in stderr_text.splitlines():
            rms_match  = rms_pattern.search(line)
            time_match = time_pattern.search(line)
            if rms_match and time_match:
                loudness_data.append(AudioLoudnessData(
                    time=float(time_match.group(1)),
                    loudness=float(rms_match.group(1)),
                ))

        return loudness_data


    async def detect_silence(
        self,
        file_path: str,
        threshold: float = -50,
        min_duration: float = 2,
    ) -> list[SilenceInterval]:
        """Znajduje przedziały ciszy poniżej progu głośności."""
        silence_intervals: list[SilenceInterval] = []
        current: dict = {}

        cmd = [
            "ffmpeg", "-i", file_path,
            "-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
            "-f", "null", "-"
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await result.communicate()

        start_re = re.compile(r"silence_start:\s*([\d.]+)")
        end_re   = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")

        for line in stderr.decode().splitlines():
            s_match = start_re.search(line)
            e_match = end_re.search(line)

            if s_match:
                current = {"start": float(s_match.group(1))}
            elif e_match and current:
                current["end"]      = float(e_match.group(1))
                current["duration"] = float(e_match.group(2))
                silence_intervals.append(SilenceInterval(**current))
                current = {}

        return silence_intervals



    async def detect_non_silence(
        self,
        file_path: str,
        threshold: float = -50,
        min_duration: float = 2,
    ) -> list[NonSilentInterval]:
     
        silence_intervals: list[SilenceInterval] = []
        total_duration: Optional[float] = None

        cmd = [
            "ffmpeg", "-i", file_path,
            "-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
            "-f", "null", "-"
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await result.communicate()
        stderr_text = stderr.decode()

        start_re    = re.compile(r"silence_start:\s*([\d.]+)")
        end_re      = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
        dur_re      = re.compile(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)")

        for line in stderr_text.splitlines():
            dur_match = dur_re.search(line)
            if dur_match:
                h, m, s = dur_match.groups()
                total_duration = int(h) * 3600 + int(m) * 60 + float(s)

            s_match = start_re.search(line)
            e_match = end_re.search(line)

            if s_match:
                silence_intervals.append(
                    SilenceInterval(start=float(s_match.group(1)), end=0, duration=0)
                )
            elif e_match and silence_intervals:
                last = silence_intervals[-1]
                last.end      = float(e_match.group(1))
                last.duration = float(e_match.group(2))

        if total_duration is None:
            meta = await self.get_metadata(file_path)
            total_duration = meta.duration

        # Odwracamy ciszę na dźwięk
        non_silent: list[NonSilentInterval] = []
        last_end = 0.0

        for silence in silence_intervals:
            if silence.start > last_end:
                non_silent.append(NonSilentInterval(
                    start=last_end,
                    end=silence.start,
                    duration=silence.start - last_end,
                ))
            last_end = silence.end

        if last_end < total_duration:
            non_silent.append(NonSilentInterval(
                start=last_end,
                end=total_duration,
                duration=total_duration - last_end,
            ))

        return non_silent

    async def get_average_silence_threshold(self, file_path: str) -> float:
        data = await self._probe_file(file_path)
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            None
        )
        if not audio_stream:
            raise ValueError("Brak strumienia audio")

        rms_level = float(audio_stream.get("rms_level", -60) or -60)
        return rms_level + 10

    async def get_average_silence_duration(self, file_path: str) -> float:
        """Zwraca średni czas trwania przerw w nagraniu."""
        threshold = await self.get_average_silence_threshold(file_path)
        segments  = await self.detect_silence(file_path, threshold + 25, min_duration=1)

        if not segments:
            return 0.0

        total = sum(s.end - s.start for s in segments)
        return total / len(segments)



    def extract_non_silent_chunks(
        self,
        silence_segments: list[SilenceInterval],
        total_duration: float,
    ) -> list[AudioChunk]:

        chunks: list[AudioChunk] = []
        last_end = 0.0

        for i, silence in enumerate(silence_segments):
            if silence.start > last_end:
                chunks.append(AudioChunk(start=last_end, end=silence.start))
            last_end = silence.end

            if i == len(silence_segments) - 1 and last_end < total_duration:
                chunks.append(AudioChunk(start=last_end, end=total_duration))

        return chunks

    async def save_non_silent_chunks(
        self, file_path: str, chunks: list[AudioChunk]
    ) -> list[str]:
        """Tnie plik audio na fizyczne pliki wg listy chunków."""
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

        async def save_chunk(chunk: AudioChunk, index: int) -> str:
            output_path = str(self.STORAGE_DIR / f"chunk_{index}.wav")
            duration = chunk.end - chunk.start
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(chunk.start),
                "-i", file_path,
                "-t", str(duration),
                output_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"Błąd cięcia chunka {index}: {stderr.decode()}")
            return output_path

        tasks = [save_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        return await asyncio.gather(*tasks)

    async def process_and_save_non_silent_chunks(self, file_path: str) -> list[str]:
        """Uproszczona metoda – używa domyślnych ustawień."""
        metadata = await self.get_metadata(file_path)
        silence  = await self.detect_silence(file_path)
        chunks   = self.extract_non_silent_chunks(silence, metadata.duration)
        return await self.save_non_silent_chunks(file_path, chunks)



    async def convert_to_ogg(self, input_path: str, output_path: str) -> None:
        """Kompresuje plik do formatu OGG Vorbis."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:a", "libvorbis",
            "-f", "ogg",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Błąd konwersji OGG: {stderr.decode()}")


    async def split(
        self,
        file_path: str,
        silence_threshold_offset: float = 25,
    ) -> list[str]:
        """
        Główna metoda – tnie nagranie na gotowe fragmenty dla Whisper.

        KROK 1: Dynamiczne ustalenie długości przerwy w tym konkretnym pliku
        KROK 2: Ustalenie progu ciszy (noise floor)
        KROK 3: Wykrycie fragmentów z mową
        KROK 4: Odfiltrowanie zbyt krótkich (< 1s)
        KROK 5: Pocięcie na fizyczne pliki WAV
        KROK 6: Konwersja do OGG + walidacja rozmiaru (max 20 MB)
        KROK 7: Zwrócenie listy ścieżek
        """

        min_silence_duration    = (await self.get_average_silence_duration(file_path)) * 0.9
        avg_silence_threshold   = await self.get_average_silence_threshold(file_path)

 
        non_silent_chunks = await self.detect_non_silence(
            file_path,
            threshold    = avg_silence_threshold + silence_threshold_offset,
            min_duration = min_silence_duration,
        )


        non_silent_chunks = [c for c in non_silent_chunks if c.duration >= 1]
   
        raw_chunks = await self.save_non_silent_chunks(file_path, [
            AudioChunk(start=c.start, end=c.end) for c in non_silent_chunks
        ])

 
        ogg_chunks: list[str] = []
        max_size_bytes = 20 * 1024 * 1024  

        for chunk_path in raw_chunks:
            ogg_path = re.sub(r"\.[^.]+$", ".ogg", chunk_path)

            if Path(chunk_path).suffix.lower() != ".ogg":
                await self.convert_to_ogg(chunk_path, ogg_path)
                os.unlink(chunk_path)
            else:
                shutil.copy(chunk_path, ogg_path)

            size = os.path.getsize(ogg_path)
            if size > max_size_bytes:
                os.unlink(ogg_path)
                raise RuntimeError(
                    f"Fragment {ogg_path} jest za duży ({size} bajtów). "
                    f"Maksimum to 20 MB."
                )

            ogg_chunks.append(ogg_path)

        return ogg_chunks
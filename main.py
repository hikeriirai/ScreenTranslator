"""Простой экранный переводчик для Windows 10/11."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import keyboard
import mss
import numpy as np
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk
from tkinter import colorchooser, ttk


LANGUAGES = {
    "Английский": "en",
    "Японский": "ja",
}

# Палитра Liquid Glass
GLASS_BG_TOP = "#1b2430"
GLASS_BG_BOTTOM = "#0c1219"
GLASS_CARD = "#18212c"
GLASS_CARD_ACTIVE = "#1e2a38"
GLASS_BORDER = "#3a4a5c"
GLASS_HIGHLIGHT = "#7fd8c6"
GLASS_TEXT = "#eaf2f6"
GLASS_MUTED = "#9db0bd"
GLASS_ACCENT = "#5eead4"
GLASS_ACCENT_DARK = "#0f766e"
GLASS_PILL = "#22303d"
HUD_STAT_LABELS = {
    "hp",
    "mp",
    "sp",
    "fp",
    "pp",
    "ap",
    "tp",
    "gp",
    "vit",
    "vita",
    "mnd",
    "mind",
    "end",
    "str",
    "dex",
    "int",
    "fth",
    "faith",
    "lck",
    "luk",
    "atk",
    "def",
    "res",
    "sta",
    "stamina",
    "stam",
    "fps",
    "armor",
    "armour",
    "crit",
    "critical",
    "dmg",
    "damage",
    "min",
    "max",
    "cost",
}
BOTTOM_UI_LABELS = {
    "auto",
    "automatic",
    "back",
    "config",
    "gallery",
    "history",
    "journal",
    "load",
    "log",
    "menu",
    "options",
    "preferences",
    "save",
    "settings",
    "skip",
}
TRANSLATION_CODES = {"en": "en", "ja": "ja"}
ARGOS_PATHS = {
    "en": (("en", "ru"),),
    "ja": (("ja", "en"), ("en", "ru")),
}
OCR_CONTEXT_QUIET_PERIOD = 0.65
OCR_CONTEXT_MAX_QUIET_PERIOD = 1.2
OCR_CONTEXT_CLEAR_PERIOD = 1.2
OVERLAY_RESIZE_RENDER_DELAY_MS = 64
COMPUTE_MODES = {"Авто": "auto", "CPU": "cpu", "GPU": "cuda"}
TRANSLATION_MODES = {"Обычный": "normal", "Визуальные новеллы": "visual_novel"}
OVERLAY_FONTS = ("Segoe UI", "Arial", "Georgia", "Yu Gothic UI", "Meiryo")
FONT_FILES = {
    "Segoe UI": "segoeui.ttf",
    "Arial": "arial.ttf",
    "Georgia": "georgia.ttf",
    "Yu Gothic UI": "YuGothR.ttc",
    "Meiryo": "meiryo.ttc",
}
TRANSPARENT_COLOR = "#010203"
SPEED_MODES = {
    "Экономно · 1,5 с · 2 потока": (1.5, 2, 720),
    "Сбалансированно · 0,8 с · 3 потока": (0.8, 3, 960),
    "Быстро · 0,4 с · 3 потока": (0.4, 3, 1280),
    "Максимально быстро · 0,2 с · 4 потока": (0.2, 4, 1600),
}
REGION_SOURCE = "Выделенная область"
ACTIVE_WINDOW_SOURCE = "Активное окно"
REGION_SETTINGS_PATH = (
    Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "region.json"
)
CUDA_DLL_HANDLES: list[Any] = []


def application_directory() -> Path:
    """Возвращает каталог приложения или исходного файла."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def packaged_self_test() -> None:
    app_dir = application_directory()
    easyocr_models = app_dir / "models" / "easyocr"
    argos_models = app_dir / "models" / "argos"
    required_ocr_models = (
        "craft_mlt_25k.pth",
        "english_g2.pth",
        "japanese_g2.pth",
    )
    missing_ocr_models = [
        name for name in required_ocr_models if not (easyocr_models / name).is_file()
    ]
    if missing_ocr_models:
        raise FileNotFoundError(
            f"Bundled EasyOCR models are missing: {', '.join(missing_ocr_models)}"
        )
    has_japanese_english = False
    has_english_russian = False
    if argos_models.is_dir():
        for item in argos_models.iterdir():
            metadata_path = item / "metadata.json"
            if not item.is_dir() or not metadata_path.is_file():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            has_japanese_english |= (
                metadata.get("from_code") == "ja"
                and metadata.get("to_code") == "en"
            )
            has_english_russian |= (
                metadata.get("from_code") == "en"
                and metadata.get("to_code") == "ru"
            )
    if not has_japanese_english or not has_english_russian:
        raise FileNotFoundError("Bundled Argos Japanese-English or English-Russian model is missing")

    os.environ["ARGOS_PACKAGES_DIR"] = str(argos_models)
    from easyocr import Reader

    Reader(
        ["en"],
        gpu=False,
        verbose=False,
        model_storage_directory=str(easyocr_models),
    )
    Reader(
        ["ja", "en"],
        gpu=False,
        verbose=False,
        model_storage_directory=str(easyocr_models),
    )

    import argostranslate.settings as argos_settings
    import argostranslate.translate as argos_translate

    argos_settings.device = "cpu"
    languages = argos_translate.get_installed_languages()
    by_code = {language.code: language for language in languages}
    if not {"ja", "en", "ru"}.issubset(by_code):
        raise RuntimeError(
            "Bundled Argos packages do not provide Japanese, English, and Russian"
        )
    japanese_to_english = by_code["ja"].get_translation(by_code["en"])
    english_to_russian = by_code["en"].get_translation(by_code["ru"])
    if japanese_to_english is None or english_to_russian is None:
        raise RuntimeError("Bundled Argos translation path ja-en-ru is unavailable")
    intermediate = japanese_to_english.translate("こんにちは")
    translated = english_to_russian.translate("I grab the handle.")
    if not intermediate.strip() or not translated.strip():
        raise RuntimeError("Bundled Argos model returned an empty translation")
    print(f"Packaged OCR models loaded; Argos ja-en-ru works: {translated}")


class OCRContextBuffer:
    """Отправляет OCR-текст после паузы в наборе контекста, а не на каждом кадре."""

    def __init__(
        self,
        quiet_period: float = OCR_CONTEXT_QUIET_PERIOD,
        clear_period: float = OCR_CONTEXT_CLEAR_PERIOD,
    ) -> None:
        self.quiet_period = quiet_period
        self.clear_period = clear_period
        self.pending_lines: list[dict[str, Any]] | None = None
        self.pending_key: tuple[tuple[str, str, bool], ...] | None = None
        self.pending_since: float | None = None
        self.emitted_key: tuple[tuple[str, str, bool], ...] | None = None
        self.empty_since: float | None = None

    @staticmethod
    def _key(
        lines: list[dict[str, Any]],
    ) -> tuple[tuple[str, str, bool], ...]:
        return tuple(
            (
                item["language"],
                normalize_ocr_text(item["text"]),
                item.get("dialogue", False),
            )
            for item in lines
        )

    def observe(self, lines: list[dict[str, Any]], now: float) -> None:
        if not lines:
            if self.pending_lines and self.pending_key != self.emitted_key:
                self.pending_since = now - self.quiet_period
            if self.empty_since is None:
                self.empty_since = now
            return

        self.empty_since = None
        key = self._key(lines)
        if key == self.pending_key:
            self.pending_lines = lines
            return
        self.pending_lines = lines
        self.pending_key = key
        self.pending_since = now

    def poll(self, now: float) -> list[dict[str, Any]] | None:
        if (
            self.pending_lines is not None
            and self.pending_key != self.emitted_key
            and self.pending_since is not None
            and now - self.pending_since >= self.quiet_period
        ):
            self.emitted_key = self.pending_key
            return self.pending_lines
        if (
            self.empty_since is not None
            and now - self.empty_since >= self.clear_period
        ):
            self.pending_lines = None
            self.pending_key = None
            self.pending_since = None
            self.emitted_key = None
            self.empty_since = None
            return []
        return None

    def next_delay(self, now: float) -> float | None:
        deadlines: list[float] = []
        if (
            self.pending_lines is not None
            and self.pending_key != self.emitted_key
            and self.pending_since is not None
        ):
            deadlines.append(self.pending_since + self.quiet_period)
        if self.empty_since is not None:
            deadlines.append(self.empty_since + self.clear_period)
        if not deadlines:
            return None
        return max(0.0, min(deadlines) - now)

    def reset(self) -> None:
        self.pending_lines = None
        self.pending_key = None
        self.pending_since = None
        self.emitted_key = None
        self.empty_since = None


def prepare_cuda_runtime() -> None:
    """Добавляет CUDA DLL из pip-пакетов в пути поиска Windows."""
    if sys.platform != "win32":
        return
    nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_dir.is_dir():
        return
    dll_dirs = [path for path in nvidia_dir.glob("*/bin") if path.is_dir()]
    if dll_dirs:
        os.environ["PATH"] = os.pathsep.join(map(str, dll_dirs)) + os.pathsep + os.environ["PATH"]
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for path in dll_dirs:
            try:
                CUDA_DLL_HANDLES.append(add_dll_directory(str(path)))
            except OSError:
                pass


def is_cuda_translation_available(ctranslate2: Any, torch: Any) -> bool:
    """Выбирает CUDA лишь когда доступны и PyTorch runtime, и устройство CTranslate2."""
    if not torch.cuda.is_available():
        return False
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except RuntimeError:
        return False


def lower_current_thread_priority() -> None:
    """Уступает CPU-приоритет интерактивным приложениям в Windows."""
    if not hasattr(ctypes, "windll"):
        return
    kernel32 = ctypes.windll.kernel32
    get_current_thread = kernel32.GetCurrentThread
    get_current_thread.restype = wintypes.HANDLE
    set_thread_priority = kernel32.SetThreadPriority
    set_thread_priority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    set_thread_priority.restype = wintypes.BOOL
    if not set_thread_priority(get_current_thread(), -1):
        raise ctypes.WinError()


def enable_dpi_awareness() -> None:
    """Отключает виртуализацию координат Windows для корректного захвата экрана."""
    if not hasattr(ctypes, "windll"):
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def get_root_window_handle(handle: int) -> int:
    """Возвращает внешний HWND верхнего уровня для обычного или Tkinter HWND."""
    try:
        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        return get_ancestor(wintypes.HWND(handle), 2) or handle
    except (AttributeError, OSError):
        return handle


def get_native_toplevel_handle(window: tk.Toplevel) -> int:
    """Возвращает внешний HWND Tkinter-окна, а не его внутреннего дочернего окна."""
    return get_root_window_handle(window.winfo_id())


def is_window_foreground(hwnd: int) -> bool:
    """Проверяет, что выбранное окно, а не другой процесс, сейчас активно."""
    if not hasattr(ctypes, "windll"):
        return True
    get_foreground = ctypes.windll.user32.GetForegroundWindow
    get_foreground.argtypes = []
    get_foreground.restype = wintypes.HWND
    foreground = get_foreground()
    return bool(foreground) and (
        get_root_window_handle(foreground) == get_root_window_handle(hwnd)
    )


def get_foreground_window_handle() -> int | None:
    """Возвращает активное прикладное окно, не рабочий стол и не панель задач."""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    get_foreground = user32.GetForegroundWindow
    get_foreground.argtypes = []
    get_foreground.restype = wintypes.HWND
    handle = get_foreground()
    if not handle:
        return None
    handle = get_root_window_handle(handle)
    class_buffer = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW(handle, class_buffer, len(class_buffer))
    if class_buffer.value in {"Progman", "WorkerW", "Shell_TrayWnd"}:
        return None
    if get_window_client_region(handle) is None:
        return None
    return handle


def set_native_window_pos(
    handle: int, x: int, y: int, width: int, height: int, flags: int
) -> None:
    """Вызывает SetWindowPos с корректными HWND-типами на 64-битной Windows."""
    set_position = ctypes.windll.user32.SetWindowPos
    set_position.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    set_position.restype = wintypes.BOOL
    if not set_position(
        wintypes.HWND(handle), wintypes.HWND(-1), x, y, width, height, flags
    ):
        raise ctypes.WinError()


def enumerate_visible_windows() -> list[tuple[str, int]]:
    """Возвращает видимые обычные окна Windows с непустым заголовком."""
    if not hasattr(ctypes, "windll"):
        return []
    user32 = ctypes.windll.user32
    found: list[tuple[str, int]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    def collect(hwnd: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        title_buffer = ctypes.create_unicode_buffer(512)
        if user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer)) <= 0:
            return True
        title = title_buffer.value.strip()
        if not title or "экранный переводчик" in title.casefold():
            return True
        region = get_window_client_region(hwnd)
        if region is not None and region["width"] >= 160 and region["height"] >= 100:
            found.append((title, hwnd))
        return True

    callback = callback_type(collect)
    user32.EnumWindows(callback, 0)
    found.sort(key=lambda item: item[0].casefold())
    return found


def get_window_client_region(hwnd: int) -> dict[str, int] | None:
    """Получает экранные координаты клиентской области выбранного окна."""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.RECT),
    ]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.POINT),
    ]
    user32.ClientToScreen.restype = wintypes.BOOL
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    point = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return {"left": point.x, "top": point.y, "width": width, "height": height}


def get_native_window_bounds(hwnd: int) -> tuple[int, int, int, int] | None:
    """Возвращает внешние экранные границы HWND с корректными 64-битными типами."""
    if not hasattr(ctypes, "windll"):
        return None
    get_rect = ctypes.windll.user32.GetWindowRect
    get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    get_rect.restype = wintypes.BOOL
    rect = wintypes.RECT()
    if not get_rect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def replace_oldest(target_queue: queue.Queue, item: Any) -> None:
    """Не позволяет медленным OCR/переводу накапливать устаревшие кадры."""
    try:
        target_queue.put_nowait(item)
    except queue.Full:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            target_queue.put_nowait(item)
        except queue.Full:
            pass


def install_argos_package(package: Any, package_path: str, argos_translate: Any) -> None:
    """Устанавливает пакет и сбрасывает кэш обнаруженных языков Argos."""
    package.install_from_path(package_path)
    argos_translate.get_installed_languages.cache_clear()


def normalize_ocr_text(text: str) -> str:
    """Убирает различия в пробелах и регистре перед дедупликацией текста."""
    return " ".join(text.casefold().split())


_FIRST_PERSON_CONTRACTIONS = {
    "you're": "I'm",
    "you've": "I've",
    "you'll": "I'll",
    "you'd": "I'd",
    "you are": "I am",
    "you were": "I was",
    "you have": "I have",
    "you has": "I have",
    "yourself": "myself",
    "yours": "mine",
    "your": "my",
}
_FIRST_PERSON_VERBS = {
    "accept", "agree", "answer", "ask", "believe", "call", "close", "come",
    "control", "do", "feel", "find", "get", "give", "go", "grab", "guess",
    "hear", "help", "hope", "know", "leave", "like", "live", "look", "love",
    "make", "mean", "move", "need", "open", "play", "remember", "run", "say",
    "see", "take", "think", "try", "understand", "want", "watch", "work",
    "write", "accepts", "believes", "calls", "closes", "comes", "feels",
    "finds", "gets", "gives", "goes", "grabs", "hears", "helps", "knows",
    "leaves", "likes", "lives", "looks", "loves", "makes", "moves", "needs",
    "opens", "plays", "remembers", "runs", "says", "sees", "takes", "thinks",
    "tries", "understands", "wants", "watches", "works", "writes",
    "am", "are", "can", "could", "did", "do", "does", "had", "has", "have",
    "is", "might", "must", "shall", "should", "was", "were", "will", "would",
    "told", "saw", "heard", "found", "gave", "went", "got", "made", "said",
}
_FIRST_PERSON_NEGATED_AUXILIARIES = {
    "can't": "can",
    "cannot": "can",
    "couldn't": "could",
    "didn't": "did",
    "doesn't": "does",
    "don't": "do",
    "hadn't": "had",
    "hasn't": "has",
    "haven't": "have",
    "isn't": "is",
    "mustn't": "must",
    "shouldn't": "should",
    "wasn't": "was",
    "weren't": "were",
    "won't": "will",
    "wouldn't": "would",
}
_FIRST_PERSON_PREPOSITIONS = {
    "about", "above", "across", "after", "against", "among", "around", "at",
    "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "by", "despite", "down", "during", "for", "from", "in", "inside", "into",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past",
    "through", "to", "toward", "under", "until", "upon", "with", "within",
    "without",
}
_FIRST_PERSON_PROTECTED_PAIRS = {'"': '"', "“": "”", "«": "»", "「": "」"}
_FIRST_PERSON_BRACKETS = {"(": ")", "[": "]", "{": "}"}


def _protected_region_end(text: str, start: int) -> int:
    char = text[start]
    if char in _FIRST_PERSON_PROTECTED_PAIRS:
        closing = _FIRST_PERSON_PROTECTED_PAIRS[char]
        index = start + 1
        while index < len(text):
            if text[index] == closing and (index == 0 or text[index - 1] != "\\"):
                return index + 1
            index += 1
        return len(text)

    stack = [_FIRST_PERSON_BRACKETS[char]]
    quote: str | None = None
    index = start + 1
    while index < len(text) and stack:
        current = text[index]
        if quote is not None:
            if current == quote and (index == 0 or text[index - 1] != "\\"):
                quote = None
        elif current in _FIRST_PERSON_PROTECTED_PAIRS:
            quote = _FIRST_PERSON_PROTECTED_PAIRS[current]
        elif current in _FIRST_PERSON_BRACKETS:
            stack.append(_FIRST_PERSON_BRACKETS[current])
        elif current == stack[-1]:
            stack.pop()
        index += 1
    return index


def _capitalize_first_person(
    replacement: str, original: str, text: str, start: int
) -> str:
    if original.isupper():
        return replacement.upper()
    prefix = text[:start]
    if not prefix.strip() or re.search(r"[.!?][\"'”»)]*\s*$", prefix):
        return replacement[0].upper() + replacement[1:]
    return replacement


def _replace_unprotected_first_person(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in _FIRST_PERSON_PROTECTED_PAIRS or char in _FIRST_PERSON_BRACKETS:
            end = _protected_region_end(text, index)
            output.append(text[index:end])
            index = end
            continue

        match = re.match(
            r"\b(?:you're|you've|you'll|you'd|you\s+(?:are|were|have|has)|"
            r"yourself|yours|your|you)\b",
            text[index:],
            flags=re.IGNORECASE,
        )
        if match is None:
            output.append(char)
            index += 1
            continue

        original = match.group(0)
        lowered = original.casefold()
        replacement = _FIRST_PERSON_CONTRACTIONS.get(lowered)
        end = index + len(original)
        if replacement is None and lowered == "you":
            before = text[:index]
            after = text[end:]
            previous = re.search(r"([A-Za-z]+)[\s,]*$", before)
            following_context = re.sub(
                r"^\s*(?:\([^()]*\)\s*)+",
                " ",
                after,
            )
            following = re.match(r"\s+([A-Za-z]+)", following_context)
            previous_word = previous.group(1).casefold() if previous else ""
            following_word = following.group(1).casefold() if following else ""
            following_word = _FIRST_PERSON_NEGATED_AUXILIARIES.get(
                following_word, following_word
            )
            if previous_word in _FIRST_PERSON_PREPOSITIONS:
                replacement = "me"
            elif following_word in _FIRST_PERSON_VERBS:
                replacement = "I"
            elif previous_word in {"am", "are", "is", "was", "were"}:
                replacement = None
            elif previous_word in _FIRST_PERSON_VERBS:
                replacement = "me"
            elif following_word and (
                not before.strip()
                or re.search(r"[.!?][\"'”»)]*\s*$", before)
            ):
                replacement = "I"
        if replacement is None:
            output.append(original)
        else:
            output.append(
                _capitalize_first_person(replacement, original, text, index)
            )
        index = end
    return "".join(output)


def to_first_person_en(text: Any) -> Any:
    """Преобразует обращение к игроку в первое лицо, сохраняя цитаты и скобки."""
    if not isinstance(text, str):
        return text
    try:
        return _replace_unprotected_first_person(text)
    except Exception:
        return text


def ocr_context_quiet_period(scan_interval: float) -> float:
    """Даёт OCR ещё один проход для продолжения реплики, не замедляя быстрые режимы."""
    return min(
        OCR_CONTEXT_MAX_QUIET_PERIOD,
        max(OCR_CONTEXT_QUIET_PERIOD, scan_interval * 1.5),
    )


def tk_position_geometry(x: int, y: int) -> str:
    """Формирует позицию окна Tk с одним знаком для каждой координаты."""
    return f"{x:+d}{y:+d}"


def place_overlay_away_from_source(
    source: dict[str, int],
    overlay_width: int,
    overlay_height: int,
    monitor: dict[str, int],
    gap: int = 16,
) -> tuple[int, int]:
    """Выбирает экранную позицию перевода с минимальным перекрытием оригинала."""
    source_left = source["left"]
    source_top = source["top"]
    source_right = source_left + source["width"]
    source_bottom = source_top + source["height"]
    monitor_left = monitor["left"]
    monitor_top = monitor["top"]
    monitor_right = monitor_left + monitor["width"]
    monitor_bottom = monitor_top + monitor["height"]

    candidates = (
        (source_left, source_bottom + gap),
        (source_left, source_top - overlay_height - gap),
        (source_right + gap, source_top),
        (source_left - overlay_width - gap, source_top),
    )
    placements: list[tuple[int, int, int, int]] = []
    for x, y in candidates:
        x = max(monitor_left, min(x, monitor_right - overlay_width))
        y = max(monitor_top, min(y, monitor_bottom - overlay_height))
        overlap_width = max(
            0,
            min(x + overlay_width, source_right) - max(x, source_left),
        )
        overlap_height = max(
            0,
            min(y + overlay_height, source_bottom) - max(y, source_top),
        )
        overlap_area = overlap_width * overlap_height
        distance = abs(x - source_left) + abs(y - source_top)
        placements.append((overlap_area, distance, x, y))
    _, _, x, y = min(placements)
    return x, y


def contains_translatable_content(text: str) -> bool:
    """Оставляет распознанные фразы, отбрасывая числа без буквенного контекста."""
    return any(character.isalpha() for character in text)


def is_ocr_candidate(text: str) -> bool:
    """Сохраняет числа до группировки, чтобы даты и количества не терялись."""
    return contains_translatable_content(text) or any(
        character.isdigit() for character in text
    )


def remove_overlapping_ruby_readings(
    lines: list[tuple[str, float, int, int, int, int]],
) -> list[tuple[str, float, int, int, int, int]]:
    """Убирает мелкие японские подсказки чтения, наложенные над основным текстом."""
    ruby_indices: set[int] = set()
    for index, line in enumerate(lines):
        _, _, top, left, bottom, right = line
        height = max(1, bottom - top)
        width = max(1, right - left)
        for other_index, other in enumerate(lines):
            if index == other_index:
                continue
            _, _, other_top, other_left, other_bottom, other_right = other
            other_height = max(1, other_bottom - other_top)
            if height > other_height * 0.65 or top >= other_top:
                continue
            overlap = max(0, min(right, other_right) - max(left, other_left))
            if overlap / min(width, max(1, other_right - other_left)) < 0.35:
                continue
            if bottom <= other_top + other_height * 0.35:
                ruby_indices.add(index)
                break
    return [line for index, line in enumerate(lines) if index not in ruby_indices]


def is_low_value_game_text(text: str) -> bool:
    """Отсекает отдельные числа и короткие HUD-показатели перед переводом."""
    tokens = re.findall(r"[^\W\d_]+|\d+(?:[.,]\d+)?%?", text.casefold())
    if not tokens:
        return True
    words = [token for token in tokens if any(character.isalpha() for character in token)]
    if not words:
        return True
    return all(word in HUD_STAT_LABELS for word in words)


def filter_bottom_navigation_lines(
    lines: list[tuple[str, float, int, int, int, int]],
    frame_height: int,
) -> list[tuple[str, float, int, int, int, int]]:
    """Отсекает нижнюю строку меню визуальной новеллы, не затрагивая реплики."""
    navigation_lines: list[tuple[str, float, int, int, int, int]] = []
    for line in lines:
        text, _, top, _, _, _ = line
        if top < frame_height * 0.78:
            continue
        tokens = re.findall(r"[a-z]+", text.casefold())
        if tokens and len(tokens) <= 4 and all(
            token in BOTTOM_UI_LABELS for token in tokens
        ):
            navigation_lines.append(line)

    remove_lines: set[int] = set()
    for line in navigation_lines:
        text_tokens = re.findall(r"[a-z]+", line[0].casefold())
        if len(text_tokens) > 1:
            remove_lines.add(id(line))
            continue
        center_y = (line[2] + line[4]) / 2
        line_height = max(1, line[4] - line[2])
        aligned_labels = sum(
            abs(center_y - (other[2] + other[4]) / 2)
            <= max(line_height, other[4] - other[2])
            for other in navigation_lines
        )
        if aligned_labels >= 2:
            remove_lines.add(id(line))

    return [line for line in lines if id(line) not in remove_lines]


def combine_dialogue_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Объединяет строки и прямоугольники одного кадра в одну реплику VN."""
    if not lines:
        raise ValueError("Нельзя объединить пустую реплику")
    bounds = [line["bounds"] for line in lines]
    left = min(item["left"] for item in bounds)
    top = min(item["top"] for item in bounds)
    right = max(item["left"] + item["width"] for item in bounds)
    bottom = max(item["top"] + item["height"] for item in bounds)
    separator = "" if lines[0]["language"] == "ja" else " "
    return {
        "text": separator.join(line["text"].strip() for line in lines),
        "language": lines[0]["language"],
        "bounds": {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        },
        "dialogue": True,
    }


def group_ocr_lines(
    lines: list[tuple[str, float, int, int, int, int]],
    *,
    paragraph_gap_ratio: float = 1.45,
    horizontal_gap_ratio: float = 4.0,
    separate_cjk_fragments: bool = False,
) -> list[tuple[str, float, int, int, int, int]]:
    """Объединяет соседние OCR-фрагменты, сохраняя раздельные экранные блоки."""
    rows: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: ((item[2] + item[4]) / 2, item[3])):
        text, confidence, top, left, bottom, right = line
        line_height = max(1, bottom - top)
        center_y = (top + bottom) / 2
        matching_row = next(
            (
                row
                for row in reversed(rows)
                if abs(center_y - row["center_y"])
                <= max(line_height, row["height"]) * 0.45
            ),
            None,
        )
        if matching_row is None:
            rows.append(
                {
                    "items": [line],
                    "top": top,
                    "bottom": bottom,
                    "height": line_height,
                    "center_y": center_y,
                }
            )
        else:
            matching_row["items"].append(line)
            matching_row["top"] = min(matching_row["top"], top)
            matching_row["bottom"] = max(matching_row["bottom"], bottom)
            matching_row["height"] = max(matching_row["height"], line_height)
            matching_row["center_y"] = (
                matching_row["top"] + matching_row["bottom"]
            ) / 2

    row_segments: list[tuple[str, float, int, int, int, int]] = []
    for row in rows:
        items = sorted(row["items"], key=lambda item: item[3])
        segments: list[list[tuple[str, float, int, int, int, int]]] = []
        for item in items:
            if (
                segments
                and item[3] - max(part[5] for part in segments[-1])
                <= max(
                    24,
                    max(item[4] - item[2], row["height"]) * horizontal_gap_ratio,
                )
            ):
                segments[-1].append(item)
            else:
                segments.append([item])
        for segment in segments:
            text_parts: list[str] = []
            for part in segment:
                part_text = part[0].strip()
                if not part_text:
                    continue
                if text_parts and part_text[0] not in ",.!?;:%)]}»":
                    text_parts.append("" if separate_cjk_fragments else " ")
                text_parts.append(part_text)
            row_segments.append(
                (
                    "".join(text_parts),
                    sum(part[1] for part in segment) / len(segment),
                    min(part[2] for part in segment),
                    min(part[3] for part in segment),
                    max(part[4] for part in segment),
                    max(part[5] for part in segment),
                )
            )

    paragraphs: list[dict[str, Any]] = []
    for segment in sorted(row_segments, key=lambda item: (item[2], item[3])):
        text, confidence, top, left, bottom, right = segment
        height = max(1, bottom - top)
        candidates: list[tuple[float, dict[str, Any]]] = []
        for paragraph in paragraphs:
            center_y = (top + bottom) / 2
            center_gap = center_y - paragraph["last_center_y"]
            line_spacing = min(height, paragraph["line_height"])
            if center_gap < 0 or center_gap > line_spacing * paragraph_gap_ratio:
                continue
            overlap = max(0, min(right, paragraph["right"]) - max(left, paragraph["left"]))
            min_width = max(1, min(right - left, paragraph["right"] - paragraph["left"]))
            aligned_left = abs(left - paragraph["anchor_left"]) <= line_spacing * 1.5
            if overlap / min_width >= 0.2 or aligned_left:
                candidates.append((center_gap, paragraph))
        if candidates:
            _, paragraph = min(candidates, key=lambda candidate: candidate[0])
            paragraph["text"] += ("" if separate_cjk_fragments else " ") + text
            paragraph["confidence_sum"] += confidence
            paragraph["count"] += 1
            paragraph["top"] = min(paragraph["top"], top)
            paragraph["left"] = min(paragraph["left"], left)
            paragraph["bottom"] = max(paragraph["bottom"], bottom)
            paragraph["right"] = max(paragraph["right"], right)
            paragraph["height"] = paragraph["bottom"] - paragraph["top"]
            paragraph["last_center_y"] = (top + bottom) / 2
            paragraph["line_height"] = height
        else:
            paragraphs.append(
                {
                    "text": text,
                    "confidence_sum": confidence,
                    "count": 1,
                    "top": top,
                    "left": left,
                    "bottom": bottom,
                    "right": right,
                    "height": height,
                    "last_center_y": (top + bottom) / 2,
                    "line_height": height,
                    "anchor_left": left,
                }
            )

    return [
        (
            paragraph["text"],
            paragraph["confidence_sum"] / paragraph["count"],
            paragraph["top"],
            paragraph["left"],
            paragraph["bottom"],
            paragraph["right"],
        )
        for paragraph in paragraphs
    ]


def load_saved_region(path: Path = REGION_SETTINGS_PATH) -> dict[str, int] | None:
    """Загружает последнюю вручную выбранную область, если файл корректен."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        region = {key: int(data[key]) for key in ("left", "top", "width", "height")}
        if region["width"] < 12 or region["height"] < 12:
            return None
        return region
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def save_region(path: Path, region: dict[str, int]) -> None:
    """Атомарно сохраняет границы, не оставляя частично записанный JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(region, ensure_ascii=False), encoding="utf-8"
    )
    temporary_path.replace(path)


class GlassSwitch(ttk.Frame):
    """Компактный переключатель в палитре стеклянной панели."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        variable: tk.BooleanVar,
        command: Callable[[], None],
    ) -> None:
        super().__init__(master, style="TFrame")
        self.variable = variable
        self.command = command
        self.indicator = tk.Canvas(
            self,
            width=46,
            height=28,
            background=GLASS_CARD,
            highlightthickness=0,
            takefocus=True,
            cursor="hand2",
        )
        self.indicator.pack(side="left")
        self.label = ttk.Label(self, text=text, style="Glass.TLabel", cursor="hand2")
        self.label.pack(side="left", padx=(8, 0))
        self.indicator.bind("<Button-1>", self._toggle)
        self.label.bind("<Button-1>", self._toggle)
        self.indicator.bind("<space>", self._toggle)
        self.indicator.bind("<Return>", self._toggle)
        self.indicator.bind("<FocusIn>", self._draw)
        self.indicator.bind("<FocusOut>", self._draw)
        self.variable.trace_add("write", self._draw)
        self._animation_id: str | None = None
        self._draw()

    def _draw(self, *_args: Any) -> None:
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
        self._render(self._target_position())

    def _target_position(self) -> float:
        return 26.0 if self.variable.get() else 4.0

    def _animate(self, start: float, target: float, frame: int = 1) -> None:
        progress = min(1.0, frame / 6)
        eased = progress * progress * (3 - 2 * progress)
        self._render(start + (target - start) * eased)
        if progress < 1.0:
            self._animation_id = self.after(
                14, lambda: self._animate(start, target, frame + 1)
            )
        else:
            self._animation_id = None

    def _render(self, knob_left: float) -> None:
        self.indicator.delete("all")
        selected = self.variable.get()
        x1, y1, x2, y2 = 2, 3, 44, 25
        track_color = GLASS_ACCENT_DARK if selected else GLASS_BORDER
        self.indicator.create_oval(
            x1, y1, x1 + 22, y2, outline="", fill=track_color
        )
        self.indicator.create_rectangle(
            x1 + 11,
            y1,
            x2 - 11,
            y2,
            outline="",
            fill=track_color,
        )
        self.indicator.create_oval(
            x2 - 22, y1, x2, y2, outline="", fill=track_color
        )
        self.indicator.create_oval(
            knob_left,
            5,
            knob_left + 18,
            23,
            outline="",
            fill=GLASS_ACCENT if selected else GLASS_TEXT,
        )
        if self.indicator.focus_get() is self.indicator:
            self.indicator.create_oval(
                1, 1, 45, 27, outline=GLASS_HIGHLIGHT, width=1
            )

    def _toggle(self, _event: tk.Event) -> str:
        start = self._target_position()
        self.variable.set(not self.variable.get())
        target = self._target_position()
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
        self._animate(start, target)
        self.command()
        return "break"


class ScreenSelector:
    """Полупрозрачное окно выделения на всём виртуальном рабочем столе."""

    def __init__(self, app: "ScreenTranslator") -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-alpha", 0.42)
        except tk.TclError:
            pass

        with mss.MSS() as screen:
            bounds = screen.monitors[0]
        self.left = bounds["left"]
        self.top = bounds["top"]
        self.width = bounds["width"]
        self.height = bounds["height"]

        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            background=GLASS_BG_BOTTOM,
            cursor="crosshair",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        instruction_width = min(620, max(280, self.width - 48))
        self.app._rounded_rectangle(
            self.canvas,
            18,
            18,
            18 + instruction_width,
            82,
            radius=16,
            outline=GLASS_BORDER,
            fill=GLASS_CARD,
            stipple="gray25",
            width=1,
        )
        self.canvas.create_text(
            36,
            30,
            anchor="nw",
            text="ВЫДЕЛЕНИЕ ОБЛАСТИ",
            fill=GLASS_HIGHLIGHT,
            font=("Segoe UI", 10, "bold"),
        )
        self.canvas.create_text(
            36,
            50,
            anchor="nw",
            text="Зажмите левую кнопку и обведите текст · Esc — отмена",
            fill=GLASS_TEXT,
            font=("Segoe UI", 10),
        )
        self.start: tuple[int, int] | None = None
        self.rectangle: int | None = None
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.resize)
        self.canvas.bind("<ButtonRelease-1>", self.finish)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.geometry(f"{self.width}x{self.height}+0+0")
        self.window.update_idletasks()
        self._place_over_virtual_desktop()
        self.app.selector_handle = get_native_toplevel_handle(self.window)
        self.window.focus_force()

    def _place_over_virtual_desktop(self) -> None:
        """WinAPI принимает отрицательные координаты виртуального рабочего стола."""
        try:
            hwnd = get_native_toplevel_handle(self.window)
            set_native_window_pos(
                hwnd, self.left, self.top, self.width, self.height, 0x0040
            )
        except (AttributeError, OSError):
            pass

    def begin(self, event: tk.Event) -> None:
        self.start = (event.x, event.y)
        if self.rectangle is not None:
            self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#68e0cf",
            width=3,
            fill="#68e0cf",
            stipple="gray25",
        )

    def resize(self, event: tk.Event) -> None:
        if self.start is not None and self.rectangle is not None:
            self.canvas.coords(
                self.rectangle, self.start[0], self.start[1], event.x, event.y
            )

    def finish(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x1, y1 = self.start
        x2, y2 = event.x, event.y
        left = min(x1, x2) + self.left
        top = min(y1, y2) + self.top
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        self.window.destroy()
        self.app.selector_handle = None
        self.app.selector = None
        self.app.root.deiconify()
        if width >= 12 and height >= 12:
            self.app.set_region({"left": left, "top": top, "width": width, "height": height})

    def cancel(self) -> None:
        self.window.destroy()
        self.app.selector_handle = None
        self.app.selector = None
        self.app.root.deiconify()


class TranslationOverlay:
    """Окно перевода; в Windows клики проходят сквозь него, кроме момента наведения."""

    def __init__(
        self,
        root: tk.Tk,
        report_capture_error: Callable[[str], None] | None = None,
    ) -> None:
        self.report_capture_error = report_capture_error
        self.capture_error_reported = False
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        self.frame = tk.Frame(
            self.window,
            background=GLASS_CARD,
            padx=14,
            pady=9,
            highlightbackground=GLASS_BORDER,
            highlightthickness=1,
        )
        self.frame.pack(fill="both", expand=True)
        self.label = tk.Label(
            self.frame,
            text="",
            background=GLASS_CARD,
            foreground=GLASS_TEXT,
            font=("Segoe UI", 16),
            justify="left",
            anchor="w",
            wraplength=700,
        )
        self.label.pack(fill="both", expand=True)
        self.window.update_idletasks()
        self._exclude_from_capture(self.window)
        for widget in (self.window, self.frame, self.label):
            widget.bind("<ButtonPress-1>", self.begin_drag)
            widget.bind("<B1-Motion>", self.drag)
        self.drag_origin: tuple[int, int, int, int] | None = None
        self.enabled = False
        self.click_through_enabled = True
        self.window.withdraw()
        self.line_windows: list[dict[str, Any]] = []
        self.window_handles: list[int] = []
        self.current_translations: list[dict[str, Any]] = []
        self.background_enabled = True
        self.font_family = "Segoe UI"
        self.font_size = 18
        self.outline_enabled = True
        self.outline_color = "#000000"
        self.outline_size = 10
        with mss.MSS() as screen:
            self.monitors = [dict(monitor) for monitor in screen.monitors]
        self._font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
        self._render_cache: OrderedDict[
            tuple[Any, ...], Image.Image
        ] = OrderedDict()

    def _exclude_from_capture(self, window: tk.Toplevel) -> None:
        """Исключает окно перевода из поддерживаемых Windows API захвата."""
        if not hasattr(ctypes, "windll"):
            return
        try:
            set_affinity = ctypes.windll.user32.SetWindowDisplayAffinity
            set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            set_affinity.restype = wintypes.BOOL
            hwnd = get_native_toplevel_handle(window)
            if not set_affinity(wintypes.HWND(hwnd), 0x00000011):
                raise ctypes.WinError()
        except (AttributeError, OSError) as error:
            if not self.capture_error_reported and self.report_capture_error is not None:
                self.capture_error_reported = True
                self.report_capture_error(
                    "Windows не смогла исключить окно перевода из захвата "
                    f"экрана: {error}. Будет использована маскировка перед OCR."
                )

    def set_style(
        self,
        *,
        background: bool,
        font_family: str,
        font_size: int,
        outline_enabled: bool,
        outline_color: str,
        outline_size: int,
    ) -> None:
        """Обновляет оформление и перерисовывает текущие переводные окна."""
        old_style = (
            self.background_enabled,
            self.font_family,
            self.font_size,
            self.outline_enabled,
            self.outline_color,
            self.outline_size,
        )
        self.background_enabled = background
        self.font_family = font_family
        self.font_size = font_size
        self.outline_enabled = outline_enabled
        self.outline_color = outline_color
        self.outline_size = outline_size
        new_style = (
            background,
            font_family,
            font_size,
            outline_enabled,
            outline_color,
            outline_size,
        )
        if new_style != old_style:
            self._render_cache.clear()
        if self.current_translations:
            self.show_translations(self.current_translations)

    def _font(
        self, size: int | None = None
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_size = self.font_size if size is None else size
        cache_key = (self.font_family, font_size)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        font_path = fonts_dir / FONT_FILES.get(self.font_family, "segoeui.ttf")
        try:
            font = ImageFont.truetype(str(font_path), font_size)
        except OSError:
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    def _render_translation(
        self,
        text: str,
        max_width: int,
        target_size: tuple[int, int] | None = None,
    ) -> Image.Image:
        """Рисует текст, опциональный фон и реальную пиксельную обводку."""
        cache_key = (
            text,
            max_width,
            target_size,
            self.background_enabled,
            self.font_family,
            self.font_size,
            self.outline_enabled,
            self.outline_color,
            self.outline_size,
        )
        cached = self._render_cache.get(cache_key)
        if cached is not None:
            self._render_cache.move_to_end(cache_key)
            return cached
        stroke_width = self.outline_size if self.outline_enabled else 0
        padding_x = 12
        padding_y = 8
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        width_limit = target_size[0] if target_size else max_width
        height_limit = target_size[1] if target_size else None
        inner_width = max(32, width_limit - padding_x * 2 - stroke_width * 2)
        font_size = self.font_size
        while True:
            font = self._font(font_size)
            wrapped_lines: list[str] = []
            for paragraph in text.splitlines() or [text]:
                if not paragraph:
                    wrapped_lines.append("")
                    continue
                current = ""
                for character in paragraph:
                    candidate = current + character
                    if current and measure.textlength(candidate, font=font) > inner_width:
                        wrapped_lines.append(current.rstrip())
                        current = character.lstrip()
                    else:
                        current = candidate
                if current:
                    wrapped_lines.append(current.rstrip())
            wrapped_text = "\n".join(wrapped_lines)
            bounds = measure.multiline_textbbox(
                (0, 0),
                wrapped_text,
                font=font,
                spacing=4,
                stroke_width=stroke_width,
            )
            content_width = max(1, bounds[2] - bounds[0] + padding_x * 2)
            content_height = max(1, bounds[3] - bounds[1] + padding_y * 2)
            if (
                height_limit is None
                or content_height <= height_limit
                or font_size <= 8
            ):
                break
            font_size -= 1
        width = target_size[0] if target_size else min(content_width, width_limit)
        height = (
            max(target_size[1], content_height)
            if target_size
            else content_height
        )
        background = (16, 24, 32, 232) if self.background_enabled else (1, 2, 3, 255)
        image = Image.new("RGBA", (width, height), background)
        draw = ImageDraw.Draw(image)
        draw.multiline_text(
            (padding_x - bounds[0], padding_y - bounds[1]),
            wrapped_text,
            font=font,
            fill="#ffffff",
            spacing=4,
            stroke_width=stroke_width,
            stroke_fill=self.outline_color,
        )
        grip_color = "#7fd8c6" if self.background_enabled else "#ffffff"
        for offset in (0, 5, 10):
            draw.line(
                (width - 5 - offset, height - 2, width - 2, height - 5 - offset),
                fill=grip_color,
                width=1,
            )
        self._render_cache[cache_key] = image
        while len(self._render_cache) > 24:
            self._render_cache.popitem(last=False)
        return image

    def _move_to(self, x: int, y: int) -> None:
        """Перемещает окно в физических координатах, включая отрицательные координаты."""
        self._move_window_to(self.window, x, y)

    def _monitor_for_bounds(self, bounds: dict[str, int]) -> dict[str, int]:
        center_x = bounds["left"] + bounds["width"] / 2
        center_y = bounds["top"] + bounds["height"] / 2
        return next(
            (
                monitor
                for monitor in self.monitors[1:]
                if monitor["left"] <= center_x < monitor["left"] + monitor["width"]
                and monitor["top"] <= center_y < monitor["top"] + monitor["height"]
            ),
            self.monitors[0],
        )

    @staticmethod
    def _move_window_to(window: tk.Toplevel, x: int, y: int) -> None:
        try:
            set_native_window_pos(
                get_native_toplevel_handle(window), x, y, 0, 0, 0x0001 | 0x0010
            )
        except (AttributeError, OSError):
            window.geometry(tk_position_geometry(x, y))

    def show(self, text: str, region: dict[str, int] | None = None) -> None:
        self.label.configure(text=text)
        if region is not None:
            width = min(max(region["width"], 360), 720)
            self.label.configure(wraplength=width - 32)
        self.window.update_idletasks()
        width = min(max(self.window.winfo_reqwidth(), 360), 760)
        height = min(max(self.window.winfo_reqheight(), 48), 220)
        if region is not None:
            with mss.MSS() as screen:
                bounds = screen.monitors[0]
            x = max(bounds["left"], min(region["left"], bounds["left"] + bounds["width"] - width))
            below = region["top"] + region["height"] + 8
            if below + height <= bounds["top"] + bounds["height"]:
                y = below
            else:
                y = max(bounds["top"], region["top"] - height - 8)
        else:
            x, y = 30, 80
        self.window.geometry(f"{width}x{height}+0+0")
        self.window.deiconify()
        self.window.lift()
        self._move_to(x, y)
        self.enabled = True
        self.set_click_through(True)

    def _create_line_window(self) -> dict[str, Any]:
        """Создаёт отдельное прозрачное окно для одной исходной строки."""
        window = tk.Toplevel(self.window)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        frame = tk.Frame(window, background=TRANSPARENT_COLOR, padx=0, pady=0)
        frame.pack(fill="both", expand=True)
        label = tk.Label(
            frame,
            text="",
            background=TRANSPARENT_COLOR,
            borderwidth=0,
            highlightthickness=0,
        )
        label.pack(fill="both", expand=True)
        record: dict[str, Any] = {
            "window": window,
            "label": label,
            "drag_origin": None,
            "drag_offset": (0, 0),
            "dialogue": False,
            "size": None,
            "position": None,
            "display_text": None,
            "click_through": None,
        }
        for widget in (window, frame, label):
            widget.bind(
                "<ButtonPress-1>",
                lambda event, item=record: self.begin_line_drag(item, event),
            )
            widget.bind(
                "<B1-Motion>",
                lambda event, item=record: self.drag_line(item, event),
            )
            widget.bind(
                "<ButtonRelease-1>",
                lambda event, item=record: self.finish_line_drag(item, event),
            )
        window.update_idletasks()
        self._exclude_from_capture(window)
        record["handle"] = get_native_toplevel_handle(window)
        self.window_handles.append(record["handle"])
        return record

    def show_translations(
        self,
        translations: list[dict[str, Any]],
        *,
        only_record: dict[str, Any] | None = None,
    ) -> None:
        """Показывает строки отдельно или единым окном VN рядом с диалогом."""
        self.current_translations = list(translations)
        if only_record is None:
            self.window.withdraw()
        while len(self.line_windows) < len(translations):
            self.line_windows.append(self._create_line_window())
        while len(self.line_windows) > len(translations):
            record = self.line_windows.pop()
            if record["handle"] in self.window_handles:
                self.window_handles.remove(record["handle"])
            record["window"].destroy()

        for record, item in zip(self.line_windows, translations):
            if only_record is not None and record is not only_record:
                continue
            bounds = item["bounds"]
            label = record["label"]
            window = record["window"]
            dialogue = item.get("dialogue", False)
            record["dialogue"] = dialogue
            if record["display_text"] != item["text"]:
                record["position"] = None
                record["display_text"] = item["text"]
            preferred_size = record.get("render_size") or record["size"]
            max_width = (
                preferred_size[0]
                if preferred_size is not None
                else 820 if dialogue else max(bounds["width"], 240)
            )
            if dialogue:
                monitor = self._monitor_for_bounds(bounds)
                max_width = min(max_width, monitor["width"] - 24)
            else:
                monitor = self._monitor_for_bounds(bounds)
            image = self._render_translation(
                item["text"],
                max_width,
                target_size=preferred_size,
            )
            photo = ImageTk.PhotoImage(image, master=window)
            record["photo"] = photo
            label.configure(image=photo)
            width, height = image.size
            window.geometry(f"{width}x{height}+0+0")
            window.attributes("-alpha", 0.97 if self.background_enabled else 1.0)
            try:
                window.attributes("-transparentcolor", TRANSPARENT_COLOR)
            except tk.TclError:
                pass
            window.deiconify()
            window.lift()
            window.update_idletasks()
            if record["position"] is not None:
                x, y = record["position"]
            else:
                offset_x, offset_y = record["drag_offset"]
                x, y = place_overlay_away_from_source(
                    bounds,
                    width,
                    height,
                    monitor,
                )
                x += offset_x
                y += offset_y
                x = max(monitor["left"], min(x, monitor["left"] + monitor["width"] - width))
                y = max(monitor["top"], min(y, monitor["top"] + monitor["height"] - height))
                record["visible_once"] = True
            self._move_window_to(window, x, y)
            if record["click_through"] is None:
                self._set_window_click_through(window, True)
                record["click_through"] = True
        # Сбрасываем флаг видимости у окон, которые больше не рисуются.
        if only_record is None:
            for record in self.line_windows[len(translations):]:
                record["visible_once"] = False
        self.enabled = bool(translations)

    def begin_line_drag(self, record: dict[str, Any], event: tk.Event) -> None:
        offset_x, offset_y = record["drag_offset"]
        resizing = (
            event.x >= record["window"].winfo_width() - 22
            and event.y >= record["window"].winfo_height() - 22
        )
        record["drag_origin"] = (
            event.x_root,
            event.y_root,
            record["window"].winfo_x(),
            record["window"].winfo_y(),
            offset_x,
            offset_y,
            resizing,
            record["window"].winfo_width(),
            record["window"].winfo_height(),
        )
        record["resizing"] = resizing

    def drag_line(self, record: dict[str, Any], event: tk.Event) -> None:
        origin = record["drag_origin"]
        if origin is None:
            return
        (
            mouse_x,
            mouse_y,
            window_x,
            window_y,
            offset_x,
            offset_y,
            resizing,
            window_width,
            window_height,
        ) = origin
        if resizing:
            record["size"] = (
                min(1920, max(160, window_width + event.x_root - mouse_x)),
                min(1200, max(72, window_height + event.y_root - mouse_y)),
            )
            if record.get("resize_after_id") is None:
                record["resize_after_id"] = record["window"].after(
                    OVERLAY_RESIZE_RENDER_DELAY_MS,
                    lambda item=record: self._render_resized_line(item),
                )
            return
        target_x = window_x + event.x_root - mouse_x
        target_y = window_y + event.y_root - mouse_y
        self._move_window_to(record["window"], target_x, target_y)
        record["position"] = (target_x, target_y)
        if record.get("dialogue"):
            record["drag_offset"] = (
                offset_x + event.x_root - mouse_x,
                offset_y + event.y_root - mouse_y,
            )

    def _render_resized_line(
        self, record: dict[str, Any], *, preview: bool = True
    ) -> None:
        record["resize_after_id"] = None
        if not record.get("resizing") or not self.current_translations:
            return
        if preview:
            width, height = record["size"]
            record["render_size"] = (
                max(160, round(width / 16) * 16),
                max(72, round(height / 12) * 12),
            )
        else:
            record["render_size"] = None
        try:
            index = self.line_windows.index(record)
        except ValueError:
            return
        if index < len(self.current_translations):
            self.show_translations(
                self.current_translations,
                only_record=record,
            )

    def finish_line_drag(self, record: dict[str, Any], _event: tk.Event) -> None:
        record["drag_origin"] = None
        was_resizing = record.get("resizing", False)
        after_id = record.get("resize_after_id")
        if after_id is not None:
            record["window"].after_cancel(after_id)
            record["resize_after_id"] = None
        if was_resizing and self.current_translations:
            self._render_resized_line(record, preview=False)
        record["resizing"] = False

    def reset_anchors(self) -> None:
        """Сбрасывает ручные смещения окон VN при смене области или источника."""
        for record in self.line_windows:
            record["drag_offset"] = (0, 0)

    def begin_drag(self, event: tk.Event) -> None:
        self.drag_origin = (
            event.x_root,
            event.y_root,
            self.window.winfo_x(),
            self.window.winfo_y(),
        )

    def drag(self, event: tk.Event) -> None:
        if self.drag_origin is None:
            return
        mouse_x, mouse_y, window_x, window_y = self.drag_origin
        self._move_to(
            window_x + event.x_root - mouse_x,
            window_y + event.y_root - mouse_y,
        )

    def set_click_through(self, enabled: bool) -> None:
        """Включает WS_EX_TRANSPARENT, но снимает его при наведении для перетаскивания."""
        if self.click_through_enabled == enabled:
            return
        self._set_window_click_through(self.window, enabled)
        self.click_through_enabled = enabled

    @staticmethod
    def _set_window_click_through(window: tk.Toplevel, enabled: bool) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = get_native_toplevel_handle(window)
            get_style = user32.GetWindowLongW
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_long
            set_style = user32.SetWindowLongW
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            set_style.restype = ctypes.c_long
            style = get_style(wintypes.HWND(hwnd), -20)
            style |= 0x00080000 | 0x00000080
            if enabled:
                style |= 0x00000020
            else:
                style &= ~0x00000020
            set_style(wintypes.HWND(hwnd), -20, style)
            set_native_window_pos(hwnd, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except (AttributeError, OSError):
            pass

    def check_pointer(self) -> None:
        windows: list[
            tuple[tk.Toplevel, bool | None, Callable[[bool], None]]
        ] = []
        if self.enabled and self.window.winfo_viewable():
            windows.append(
                (self.window, self.click_through_enabled, self.set_click_through)
            )
        windows.extend(
            (
                record["window"],
                record["click_through"],
                lambda enabled, item=record: self._set_line_click_through(
                    item, enabled
                ),
            )
            for record in self.line_windows
            if record["window"].winfo_viewable()
        )
        if not windows:
            return
        try:
            point = wintypes.POINT()
            get_cursor_pos = ctypes.windll.user32.GetCursorPos
            get_cursor_pos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            get_cursor_pos.restype = wintypes.BOOL
            if not get_cursor_pos(ctypes.byref(point)):
                return
            for window, click_through_enabled, set_click_through in windows:
                left = window.winfo_rootx()
                top = window.winfo_rooty()
                inside = (
                    left <= point.x < left + window.winfo_width()
                    and top <= point.y < top + window.winfo_height()
                )
                desired = not inside
                if desired != click_through_enabled:
                    set_click_through(desired)
        except (AttributeError, OSError, tk.TclError):
            pass

    def _set_line_click_through(
        self, record: dict[str, Any], enabled: bool
    ) -> None:
        self._set_window_click_through(record["window"], enabled)
        record["click_through"] = enabled


class ScreenTranslator:
    """Связывает панель, захват экрана, OCR, перевод и горячие клавиши."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Экранный переводчик")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Map>", self._restore_custom_chrome, add="+")
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.frames: queue.Queue[tuple[dict[str, int], bytes, int, int]] = queue.Queue(maxsize=1)
        self.texts: queue.Queue[list[dict[str, Any]]] = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.force_capture = threading.Event()
        self.context_reset_event = threading.Event()
        self.paused = threading.Event()
        self.paused.set()
        self.region: dict[str, int] | None = load_saved_region()
        self.selected_language = "en"
        self.compute_mode = "auto"
        self.scan_interval, self.cpu_threads, self.max_ocr_dimension = SPEED_MODES[
            "Сбалансированно · 0,8 с · 3 потока"
        ]
        self.translation_mode = "visual_novel"
        self.first_person_enabled = True
        self.overlay_background = True
        self.overlay_font_family = "Segoe UI"
        self.overlay_font_size = 18
        self.overlay_outline_enabled = True
        self.overlay_outline_color = "#000000"
        self.overlay_outline_size = 10
        self.target_window_hwnd: int | None = None
        self.selector_handle: int | None = None
        self.window_values: dict[str, int] = {}
        self.latest_text: list[dict[str, Any]] | None = None
        self.selector: ScreenSelector | None = None
        self.overlay = TranslationOverlay(
            self.root,
            report_capture_error=lambda message: self.messages.put(("notice", message)),
        )
        self.own_window_handles = (
            get_native_toplevel_handle(self.root),
            get_native_toplevel_handle(self.overlay.window),
        )
        self._build_panel()
        self.root.after(60, self._draw_glass_background)
        if self.region is not None:
            self.follow_foreground = False
            self.source_var.set(REGION_SOURCE)
            self.paused.clear()
            self.pause_button.configure(text="Пауза (F9)")
            self.status_var.set(
                f"Восстановлена область {self.region['width']}×{self.region['height']}."
            )
        self._start_workers()
        self._install_hotkeys()
        self.root.after(100, self._process_messages)

    def _build_panel(self) -> None:
        """Создаёт панель в стиле Liquid Glass: тёмное размытое «стекло» и капсулы."""
        self.root.configure(background=GLASS_BG_BOTTOM)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=GLASS_CARD)
        style.configure(
            "Glass.TLabel", background=GLASS_CARD, foreground=GLASS_TEXT, font=("Segoe UI", 9)
        )
        style.configure(
            "Muted.TLabel", background=GLASS_CARD, foreground=GLASS_MUTED, font=("Segoe UI", 8)
        )
        style.configure(
            "Header.TLabel",
            background=GLASS_CARD,
            foreground=GLASS_HIGHLIGHT,
            font=("Segoe UI Semibold", 13, "bold"),
        )
        style.configure(
            "TButton",
            background=GLASS_PILL,
            foreground=GLASS_TEXT,
            borderwidth=0,
            focusthickness=0,
            padding=(10, 7),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TButton",
            background=[("pressed", GLASS_ACCENT_DARK), ("active", GLASS_CARD_ACTIVE)],
            foreground=[("disabled", GLASS_MUTED), ("!disabled", "#ffffff")],
        )
        style.configure(
            "Accent.TButton",
            background=GLASS_ACCENT,
            foreground="#04201c",
            borderwidth=0,
            focusthickness=0,
            padding=(10, 7),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", GLASS_ACCENT_DARK), ("active", "#7ef0dc")],
            foreground=[("disabled", GLASS_MUTED), ("!disabled", "#04201c")],
        )
        style.configure(
            "TCombobox",
            fieldbackground=GLASS_CARD_ACTIVE,
            background=GLASS_CARD_ACTIVE,
            foreground=GLASS_TEXT,
            arrowcolor=GLASS_ACCENT,
            bordercolor=GLASS_BORDER,
            lightcolor=GLASS_BORDER,
            darkcolor=GLASS_BORDER,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", GLASS_CARD_ACTIVE), ("focus", GLASS_CARD_ACTIVE)],
            foreground=[("readonly", GLASS_TEXT), ("disabled", GLASS_MUTED)],
            selectbackground=[("readonly", GLASS_ACCENT)],
            selectforeground=[("readonly", "#04201c")],
            bordercolor=[("focus", GLASS_ACCENT), ("!focus", GLASS_BORDER)],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=GLASS_CARD_ACTIVE,
            background=GLASS_CARD_ACTIVE,
            foreground=GLASS_TEXT,
            arrowcolor=GLASS_ACCENT,
            bordercolor=GLASS_BORDER,
            padding=4,
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("focus", GLASS_CARD_ACTIVE)],
            foreground=[("disabled", GLASS_MUTED)],
            bordercolor=[("focus", GLASS_ACCENT), ("!focus", GLASS_BORDER)],
        )
        self.root.option_add("*TCombobox*Listbox.background", GLASS_CARD_ACTIVE)
        self.root.option_add("*TCombobox*Listbox.foreground", GLASS_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", GLASS_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#04201c")

        # Canvas-фон для имитации «стекла»: вертикальный градиент + мягкое свечение.
        self.panel_canvas = tk.Canvas(
            self.root,
            highlightthickness=0,
            bd=0,
            background=GLASS_BG_BOTTOM,
        )
        self.panel_canvas.pack(fill="both", expand=True)
        self.panel_canvas.bind("<Configure>", self._draw_glass_background)

        panel = ttk.Frame(self.panel_canvas)
        self.panel_window = self.panel_canvas.create_window(
            (0, 0), window=panel, anchor="nw", tags="panel"
        )
        panel.columnconfigure(1, weight=1)

        chrome = ttk.Frame(panel)
        chrome.configure(cursor="fleur")
        chrome.grid(row=0, column=0, columnspan=2, pady=(0, 2), sticky="ew")
        chrome.columnconfigure(0, weight=1)
        chrome_title = ttk.Label(
            chrome,
            text="ЭКРАННЫЙ ПЕРЕВОДЧИК",
            style="Header.TLabel",
            cursor="fleur",
        )
        chrome_title.grid(row=0, column=0, sticky="w")
        ttk.Button(
            chrome,
            text="−",
            width=3,
            command=self._minimize_panel,
        ).grid(row=0, column=1, padx=(8, 2))
        ttk.Button(
            chrome,
            text="×",
            width=3,
            command=self.close,
        ).grid(row=0, column=2, padx=(2, 0))
        for widget in (chrome, chrome_title):
            widget.bind("<ButtonPress-1>", self._begin_window_drag)
            widget.bind("<B1-Motion>", self._drag_window)
        subtitle_label = ttk.Label(
            panel, text="Liquid Glass · локальный OCR и перевод", style="Muted.TLabel"
        )
        subtitle_label.configure(cursor="fleur")
        subtitle_label.grid(row=1, column=0, columnspan=2, pady=(0, 10), sticky="w")
        subtitle_label.bind("<ButtonPress-1>", self._begin_window_drag)
        subtitle_label.bind("<B1-Motion>", self._drag_window)

        ttk.Label(panel, text="Источник захвата", style="Glass.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.source_var = tk.StringVar(value=ACTIVE_WINDOW_SOURCE)
        self.source_box = ttk.Combobox(
            panel,
            textvariable=self.source_var,
            values=(ACTIVE_WINDOW_SOURCE, REGION_SOURCE),
            state="readonly",
            width=24,
        )
        self.source_box.grid(row=2, column=1, padx=(12, 0), sticky="ew")
        self.source_box.bind("<<ComboboxSelected>>", self._source_changed)
        ttk.Button(panel, text="Обновить окна", command=self._refresh_windows).grid(
            row=3, column=0, columnspan=2, pady=(6, 0), sticky="ew"
        )

        ttk.Label(panel, text="Язык оригинала", style="Glass.TLabel").grid(
            row=4, column=0, pady=(10, 0), sticky="w"
        )
        self.language_var = tk.StringVar(value="Английский")
        language_box = ttk.Combobox(
            panel,
            textvariable=self.language_var,
            values=tuple(LANGUAGES),
            state="readonly",
            width=17,
        )
        language_box.grid(row=4, column=1, padx=(12, 0), pady=(10, 0), sticky="ew")
        language_box.bind("<<ComboboxSelected>>", self._language_changed)

        ttk.Label(panel, text="Устройство обработки", style="Glass.TLabel").grid(
            row=5, column=0, pady=(10, 0), sticky="w"
        )
        self.compute_var = tk.StringVar(value="Авто")
        compute_box = ttk.Combobox(
            panel,
            textvariable=self.compute_var,
            values=tuple(COMPUTE_MODES),
            state="readonly",
            width=17,
        )
        compute_box.grid(row=5, column=1, padx=(12, 0), pady=(10, 0), sticky="ew")
        compute_box.bind("<<ComboboxSelected>>", self._compute_changed)

        ttk.Label(panel, text="Частота проверки", style="Glass.TLabel").grid(
            row=6, column=0, pady=(10, 0), sticky="w"
        )
        self.speed_var = tk.StringVar(value="Сбалансированно · 0,8 с · 3 потока")
        speed_box = ttk.Combobox(
            panel,
            textvariable=self.speed_var,
            values=tuple(SPEED_MODES),
            state="readonly",
            width=20,
        )
        speed_box.grid(row=6, column=1, padx=(12, 0), pady=(10, 0), sticky="ew")
        speed_box.bind("<<ComboboxSelected>>", self._speed_changed)

        ttk.Label(panel, text="Режим перевода", style="Glass.TLabel").grid(
            row=7, column=0, pady=(10, 0), sticky="w"
        )
        self.mode_var = tk.StringVar(value="Визуальные новеллы")
        mode_box = ttk.Combobox(
            panel,
            textvariable=self.mode_var,
            values=tuple(TRANSLATION_MODES),
            state="readonly",
            width=20,
        )
        mode_box.grid(row=7, column=1, padx=(12, 0), pady=(10, 0), sticky="ew")
        mode_box.bind("<<ComboboxSelected>>", self._translation_mode_changed)

        self.first_person_var = tk.BooleanVar(value=True)
        GlassSwitch(
            panel,
            text="От первого лица (VN)",
            variable=self.first_person_var,
            command=self._first_person_changed,
        ).grid(row=8, column=0, columnspan=2, pady=(10, 0), sticky="w")

        self.background_var = tk.BooleanVar(value=True)
        GlassSwitch(
            panel,
            text="Тёмный фон перевода",
            variable=self.background_var,
            command=self._overlay_style_changed,
        ).grid(row=9, column=0, columnspan=2, pady=(10, 0), sticky="w")

        ttk.Label(panel, text="Шрифт перевода", style="Glass.TLabel").grid(
            row=10, column=0, pady=(10, 0), sticky="w"
        )
        self.font_var = tk.StringVar(value=self.overlay_font_family)
        font_box = ttk.Combobox(
            panel,
            textvariable=self.font_var,
            values=OVERLAY_FONTS,
            state="readonly",
            width=16,
        )
        font_box.grid(row=10, column=1, padx=(12, 0), pady=(10, 0), sticky="ew")
        font_box.bind("<<ComboboxSelected>>", self._overlay_style_changed)

        ttk.Label(panel, text="Размер шрифта", style="Glass.TLabel").grid(
            row=11, column=0, pady=(10, 0), sticky="w"
        )
        self.font_size_var = tk.StringVar(value=str(self.overlay_font_size))
        font_size_box = ttk.Spinbox(
            panel,
            textvariable=self.font_size_var,
            from_=10,
            to=48,
            width=6,
            command=self._overlay_style_changed,
        )
        font_size_box.grid(row=11, column=1, padx=(12, 0), pady=(10, 0), sticky="w")
        font_size_box.bind("<FocusOut>", self._overlay_style_changed)
        font_size_box.bind("<Return>", self._overlay_style_changed)

        outline_row = ttk.Frame(panel)
        outline_row.grid(row=12, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        self.outline_var = tk.BooleanVar(value=True)
        GlassSwitch(
            outline_row,
            text="Обводка",
            variable=self.outline_var,
            command=self._overlay_style_changed,
        ).pack(side="left")
        self.outline_color_button = ttk.Button(
            outline_row,
            text="Чёрная",
            command=self._choose_outline_color,
            width=10,
        )
        self.outline_color_button.pack(side="left", padx=(10, 0))
        ttk.Label(outline_row, text="Толщина", style="Glass.TLabel").pack(
            side="left", padx=(10, 4)
        )
        self.outline_size_var = tk.StringVar(value=str(self.overlay_outline_size))
        outline_size_box = ttk.Spinbox(
            outline_row,
            textvariable=self.outline_size_var,
            from_=0,
            to=20,
            width=4,
            command=self._overlay_style_changed,
        )
        outline_size_box.pack(side="left")
        outline_size_box.bind("<FocusOut>", self._overlay_style_changed)
        outline_size_box.bind("<Return>", self._overlay_style_changed)

        buttons = ttk.Frame(panel)
        buttons.grid(row=13, column=0, columnspan=2, pady=(14, 8), sticky="ew")
        ttk.Button(
            buttons, text="Выбрать область (F8)", command=self.select_region, style="Accent.TButton"
        ).pack(side="left", padx=(0, 6))
        self.pause_button = ttk.Button(
            buttons, text="Продолжить (F9)", command=self.toggle_pause
        )
        self.pause_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Выход (F10)", command=self.close).pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="F8 — выбрать область экрана")
        ttk.Label(
            panel,
            textvariable=self.status_var,
            wraplength=390,
            style="Muted.TLabel",
            justify="left",
        ).grid(row=14, column=0, columnspan=2, sticky="w")

        self._draw_glass_background()
        self._overlay_style_changed()
        self._refresh_windows()
        self.root.update_idletasks()
        width = max(self.root.winfo_reqwidth(), 500)
        height = max(self.root.winfo_reqheight(), 620)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)
        self.root.after(60, self._draw_glass_background)

    @staticmethod
    def _rounded_rectangle(
        canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs: Any
    ) -> None:
        """Рисует скруглённый прямоугольник через сглаженный полигон."""
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        canvas.create_polygon(points, smooth=True, **kwargs)

    def _begin_window_drag(self, event: tk.Event) -> None:
        self._panel_drag_origin = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )

    def _minimize_panel(self) -> None:
        self.root.overrideredirect(False)
        self.root.iconify()

    def _restore_custom_chrome(self, _event: tk.Event) -> None:
        if self.root.state() == "normal":
            self.root.after_idle(lambda: self.root.overrideredirect(True))

    def _drag_window(self, event: tk.Event) -> None:
        origin = getattr(self, "_panel_drag_origin", None)
        if origin is None:
            return
        mouse_x, mouse_y, window_x, window_y = origin
        x = window_x + event.x_root - mouse_x
        y = window_y + event.y_root - mouse_y
        set_native_window_pos(
            get_native_toplevel_handle(self.root.winfo_id()),
            x,
            y,
            self.root.winfo_width(),
            self.root.winfo_height(),
            0x0014,
        )

    def _draw_glass_background(self, _event: tk.Event | None = None) -> None:
        """Рисует градиент, свечения и скруглённую стеклянную карточку под содержимым."""
        canvas = self.panel_canvas
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        canvas.delete("glass")
        # Вертикальный градиент «стекла».
        top = self.root.winfo_rgb(GLASS_BG_TOP)
        bottom = self.root.winfo_rgb(GLASS_BG_BOTTOM)
        steps = 48
        for index in range(steps):
            ratio = index / (steps - 1)
            color = "#%02x%02x%02x" % tuple(
                int((top[channel] * (1 - ratio) + bottom[channel] * ratio) / 256)
                for channel in range(3)
            )
            y1 = int(height * index / steps)
            y2 = int(height * (index + 1) / steps) + 1
            canvas.create_rectangle(0, y1, width, y2, outline="", fill=color, tags="glass")
        # Мягкие акцентные свечения по углам.
        canvas.create_oval(
            -width * 0.25, -height * 0.15, width * 0.5, height * 0.35,
            outline="", fill="#12323a", tags="glass",
        )
        canvas.create_oval(
            width * 0.55, height * 0.7, width * 1.25, height * 1.2,
            outline="", fill="#102a3a", tags="glass",
        )
        # Стеклянная карточка со скруглением и светлой обводкой.
        margin = 12
        self._rounded_rectangle(
            canvas,
            margin, margin, width - margin, height - margin,
            radius=22,
            outline=GLASS_BORDER,
            fill=GLASS_CARD,
            width=1,
            tags="glass",
        )
        # Тонкий блик сверху карточки.
        canvas.create_line(
            margin + 24, margin + 2, width - margin - 24, margin + 2,
            fill="#3c4d60", width=1, tags="glass",
        )
        canvas.tag_lower("glass")
        # Содержимое — поверх стекла.
        canvas.coords("panel", margin + 22, margin + 20)
        canvas.itemconfigure(
            self.panel_window,
            width=max(1, width - 2 * (margin + 22)),
        )
        canvas.tag_raise("panel")

    def _refresh_windows(self) -> None:
        """Обновляет список окон, исключая собственную панель переводчика."""
        previous = (
            self.source_var.get()
            if hasattr(self, "source_var")
            else ACTIVE_WINDOW_SOURCE
        )
        self.window_values.clear()
        labels = [ACTIVE_WINDOW_SOURCE, REGION_SOURCE]
        used_labels: set[str] = set()
        for title, hwnd in enumerate_visible_windows():
            label = title
            if label in used_labels:
                label = f"{title} [{hwnd:#x}]"
            used_labels.add(label)
            labels.append(label)
            self.window_values[label] = hwnd
        self.source_box.configure(values=labels)
        if previous not in labels:
            self.source_var.set(ACTIVE_WINDOW_SOURCE)
            self.target_window_hwnd = None
            self.follow_foreground = True
        else:
            self.source_var.set(previous)
            self.follow_foreground = previous == ACTIVE_WINDOW_SOURCE
            refreshed_hwnd = self.window_values.get(previous)
            if refreshed_hwnd != self.target_window_hwnd:
                self.target_window_hwnd = refreshed_hwnd
                self.region = (
                    get_window_client_region(refreshed_hwnd)
                    if refreshed_hwnd is not None
                    else None
                )
                self.context_reset_event.set()
                self.force_capture.set()
                self.status_var.set("Список окон обновлён; захват переподключён.")

    def _source_changed(self, _event: tk.Event) -> None:
        source = self.source_var.get()
        self.follow_foreground = source == ACTIVE_WINDOW_SOURCE
        self.target_window_hwnd = self.window_values.get(source)
        self.latest_text = None
        self.context_reset_event.set()
        self.force_capture.set()
        self.overlay.reset_anchors()
        if self.follow_foreground:
            self.paused.clear()
            self.pause_button.configure(text="Пауза (F9)")
            self.status_var.set("Захват активного окна. Переключитесь в игру.")
            return
        if self.target_window_hwnd is None:
            self.status_var.set("Источник: выделенная область. Нажмите F8.")
            return
        self.region = get_window_client_region(self.target_window_hwnd)
        self.latest_text = None
        self.paused.clear()
        self.pause_button.configure(text="Пауза (F9)")
        self.status_var.set(f"Захват окна «{source}» запущен.")

    def _language_changed(self, _event: tk.Event) -> None:
        self.selected_language = LANGUAGES[self.language_var.get()]
        self.context_reset_event.set()
        self.force_capture.set()
        self.status_var.set("Язык изменён. Новые кадры будут распознаны этим языком.")

    def _compute_changed(self, _event: tk.Event) -> None:
        self.compute_mode = COMPUTE_MODES[self.compute_var.get()]
        if self.latest_text is not None:
            replace_oldest(self.texts, self.latest_text)
        if self.compute_mode == "cpu":
            self.status_var.set("OCR и перевод будут выполняться на CPU.")
        elif self.compute_mode == "auto":
            self.status_var.set("Авто: GPU для OCR и перевода, если CUDA доступна.")
        else:
            self.status_var.set("GPU выбран для OCR и перевода; при ошибке будет CPU fallback.")

    def _speed_changed(self, _event: tk.Event) -> None:
        self.scan_interval, self.cpu_threads, self.max_ocr_dimension = SPEED_MODES[
            self.speed_var.get()
        ]
        self.status_var.set(
            f"Скорость: {self.speed_var.get()}; CPU OCR ограничен до {self.cpu_threads} потока."
        )

    def _translation_mode_changed(self, _event: tk.Event) -> None:
        self.translation_mode = TRANSLATION_MODES[self.mode_var.get()]
        self.context_reset_event.set()
        self.force_capture.set()
        if self.latest_text is not None:
            replace_oldest(self.texts, self.latest_text)
        if self.translation_mode == "visual_novel":
            self.status_var.set(
                "VN: весь диалог одним окном; цифры сохраняются, первое лицо включено."
                if self.first_person_enabled
                else "VN: весь диалог одним окном; цифры сохраняются."
            )
        else:
            self.status_var.set("Обычный режим: отдельное окно на каждую строку.")

    def _first_person_changed(self) -> None:
        self.first_person_enabled = self.first_person_var.get()
        if self.translation_mode == "visual_novel":
            self.context_reset_event.set()
            if self.latest_text is not None:
                replace_oldest(self.texts, self.latest_text)
            self.status_var.set(
                "VN: местоимения игрока преобразуются в первое лицо."
                if self.first_person_enabled
                else "VN: преобразование первого лица отключено."
            )

    def _overlay_style_changed(self, _event: tk.Event | None = None) -> None:
        self.overlay_background = self.background_var.get()
        self.overlay_font_family = self.font_var.get()
        try:
            self.overlay_font_size = min(48, max(10, int(self.font_size_var.get())))
        except ValueError:
            self.overlay_font_size = 18
            self.font_size_var.set("18")
        self.overlay_outline_enabled = self.outline_var.get()
        try:
            self.overlay_outline_size = min(20, max(0, int(self.outline_size_var.get())))
        except ValueError:
            self.overlay_outline_size = 10
            self.outline_size_var.set("10")
        self.overlay.set_style(
            background=self.overlay_background,
            font_family=self.overlay_font_family,
            font_size=self.overlay_font_size,
            outline_enabled=self.overlay_outline_enabled,
            outline_color=self.overlay_outline_color,
            outline_size=self.overlay_outline_size,
        )

    def _choose_outline_color(self) -> None:
        selected = colorchooser.askcolor(
            color=self.overlay_outline_color, title="Цвет обводки"
        )[1]
        if selected:
            self.overlay_outline_color = selected
            self.outline_color_button.configure(text=selected.upper())
            self._overlay_style_changed()

    def _start_workers(self) -> None:
        threading.Thread(target=self._capture_loop, name="screen-capture", daemon=True).start()
        threading.Thread(target=self._ocr_loop, name="ocr-worker", daemon=True).start()
        threading.Thread(target=self._translation_loop, name="translation-worker", daemon=True).start()

    def _install_hotkeys(self) -> None:
        try:
            keyboard.add_hotkey("F8", lambda: self.messages.put(("hotkey", "select")))
            keyboard.add_hotkey("F9", lambda: self.messages.put(("hotkey", "pause")))
            keyboard.add_hotkey("F10", lambda: self.messages.put(("hotkey", "exit")))
            self.hotkeys_ready = True
        except Exception as error:
            self.hotkeys_ready = False
            self.status_var.set(f"Не удалось включить горячие клавиши: {error}")

    def set_region(self, region: dict[str, int]) -> None:
        self.follow_foreground = False
        self.target_window_hwnd = None
        self.source_var.set(REGION_SOURCE)
        self.context_reset_event.set()
        self.overlay.reset_anchors()
        self.region = {key: int(region[key]) for key in ("left", "top", "width", "height")}
        save_error: OSError | None = None
        try:
            save_region(REGION_SETTINGS_PATH, self.region)
        except OSError as error:
            save_error = error
        self.paused.clear()
        self.pause_button.configure(text="Пауза (F9)")
        if save_error is None:
            self.status_var.set(
                f"Область {self.region['width']}×{self.region['height']} сохранена."
            )
        else:
            self.status_var.set(f"Область выбрана, но не сохранена: {save_error}")
        self.overlay.show("Область выбрана. Ожидание текста…", region)

    def select_region(self) -> None:
        if self.selector is not None:
            return
        self.root.withdraw()
        try:
            self.selector = ScreenSelector(self)
        except Exception as error:
            self.selector = None
            self.root.deiconify()
            self.status_var.set(f"Не удалось выбрать область: {error}")

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            self.pause_button.configure(text="Пауза (F9)")
            self.status_var.set("Перевод продолжен.")
        else:
            self.paused.set()
            self.pause_button.configure(text="Продолжить (F9)")
            self.status_var.set("Перевод приостановлен.")

    def _capture_loop(self) -> None:
        """Сравнивает кадры выбранного окна или области с заданной частотой."""
        previous_hash = b""
        previous_region: dict[str, int] | None = None
        target_was_foreground: bool | None = None
        try:
            with mss.MSS() as screen:
                while not self.stop_event.is_set():
                    if self.follow_foreground:
                        target_hwnd = get_foreground_window_handle()
                        own_handles = {
                            *self.own_window_handles,
                            *self.overlay.window_handles,
                        }
                        if self.selector_handle is not None:
                            own_handles.add(self.selector_handle)
                        if target_hwnd in own_handles:
                            target_hwnd = None
                        target_is_foreground = target_hwnd is not None
                    else:
                        target_hwnd = self.target_window_hwnd
                        target_is_foreground = (
                            is_window_foreground(target_hwnd)
                            if target_hwnd is not None
                            else True
                        )
                    if target_is_foreground != target_was_foreground:
                        target_was_foreground = target_is_foreground
                        previous_hash = b""
                        if self.follow_foreground or self.target_window_hwnd is not None:
                            status = (
                                "Захват выбранного окна активен."
                                if target_is_foreground
                                else "Ожидаю активное окно…"
                            )
                            self.messages.put(("status", status))
                    if not target_is_foreground:
                        time.sleep(self.scan_interval)
                        continue
                    region = (
                        get_window_client_region(target_hwnd)
                        if target_hwnd is not None
                        else None if self.follow_foreground else self.region
                    )
                    if self.paused.is_set() or region is None:
                        time.sleep(0.12)
                        continue
                    if region != previous_region:
                        previous_hash = b""
                        previous_region = region.copy()
                    try:
                        shot = screen.grab(region)
                        image_bytes = self._mask_own_windows(
                            shot.rgb, shot.width, shot.height, region
                        )
                        current_hash = hashlib.blake2b(image_bytes, digest_size=16).digest()
                        if current_hash != previous_hash or self.force_capture.is_set():
                            self.force_capture.clear()
                            previous_hash = current_hash
                            replace_oldest(
                                self.frames,
                                (region.copy(), image_bytes, shot.width, shot.height),
                            )
                    except Exception as error:
                        self.messages.put(("notice", f"Ошибка захвата экрана: {error}"))
                        time.sleep(0.6)
                    time.sleep(self.scan_interval)
        except Exception as error:
            self.messages.put(("notice", f"Не удалось запустить захват экрана: {error}"))

    def _mask_own_windows(
        self, image_bytes: bytes, width: int, height: int, region: dict[str, int]
    ) -> bytes:
        """Закрашивает собственные верхние окна, попавшие в захваченный экранный кадр."""
        masked_image: np.ndarray | None = None
        window_handles = (*self.own_window_handles, *self.overlay.window_handles)
        if self.selector_handle is not None:
            window_handles = (*window_handles, self.selector_handle)
        for hwnd in window_handles:
            bounds = get_native_window_bounds(hwnd)
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            x1 = max(0, left - region["left"])
            y1 = max(0, top - region["top"])
            x2 = min(width, right - region["left"])
            y2 = min(height, bottom - region["top"])
            if x1 >= x2 or y1 >= y2:
                continue
            if masked_image is None:
                masked_image = np.frombuffer(image_bytes, dtype=np.uint8).reshape(
                    height, width, 3
                ).copy()
            masked_image[y1:y2, x1:x2] = (16, 24, 32)
        return image_bytes if masked_image is None else masked_image.tobytes()

    @staticmethod
    def _prepare_image(
        image_bytes: bytes, width: int, height: int, max_dimension: int = 1600
    ) -> np.ndarray:
        """Ограничивает размер кадра и повышает контраст без лишнего апскейла."""
        image = Image.frombytes("RGB", (width, height), image_bytes)
        scale = min(1.0, max_dimension / max(width, height))
        if scale < 0.99:
            image = image.resize(
                (int(width * scale), int(height * scale)), Image.Resampling.LANCZOS
            )
        image = ImageOps.autocontrast(image.convert("L"))
        return np.asarray(image)

    def _ocr_loop(self) -> None:
        """Создаёт модели только в рабочем потоке и сохраняет загруженные Reader."""
        try:
            lower_current_thread_priority()
        except OSError as error:
            self.messages.put(
                ("status", f"Не удалось снизить приоритет OCR-потока: {error}")
            )
        try:
            prepare_cuda_runtime()
            from easyocr import Reader
            import torch
            import cv2
        except Exception as error:
            self.messages.put(("notice", f"Не удалось загрузить EasyOCR: {error}"))
            return

        cv2.setNumThreads(1)
        cpu_thread_count = min(
            self.cpu_threads,
            max(1, os.cpu_count() or 1),
        )
        try:
            torch.set_num_threads(cpu_thread_count)
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass

        readers: dict[str, Any] = {}
        reader_devices: dict[str, str] = {}
        easyocr_model_directory = application_directory() / "models" / "easyocr"
        reader_options = (
            {"model_storage_directory": str(easyocr_model_directory)}
            if easyocr_model_directory.is_dir()
            else {}
        )
        context_buffer = OCRContextBuffer()
        last_reported_ocr_device: str | None = None
        next_ocr_at = 0.0
        while not self.stop_event.is_set():
            context_buffer.quiet_period = ocr_context_quiet_period(self.scan_interval)
            if self.context_reset_event.is_set():
                context_buffer.reset()
                self.context_reset_event.clear()
            now = time.monotonic()
            ready_lines = context_buffer.poll(now)
            if ready_lines is not None:
                self.latest_text = ready_lines
                if ready_lines:
                    replace_oldest(self.texts, ready_lines)
                    self.messages.put(
                        ("status", "Контекст стабилизировался; выполняется перевод…")
                    )
                else:
                    self.messages.put(("translations", []))
                    self.messages.put(
                        ("status", "Текст исчез. Ожидание новых надписей…")
                    )

            wait = next_ocr_at - now
            context_wait = context_buffer.next_delay(now)
            if context_wait is not None:
                wait = min(wait, context_wait)
            if wait > 0 and self.stop_event.wait(wait):
                return
            try:
                timeout = 0.3
                context_wait = context_buffer.next_delay(time.monotonic())
                if context_wait is not None:
                    timeout = min(timeout, context_wait)
                region, image_bytes, width, height = self.frames.get(timeout=timeout)
            except queue.Empty:
                continue
            next_ocr_at = time.monotonic() + self.scan_interval
            try:
                cpu_thread_count = min(
                    self.cpu_threads,
                    max(1, os.cpu_count() or 1),
                )
                if torch.get_num_threads() != cpu_thread_count:
                    torch.set_num_threads(cpu_thread_count)
                ocr_device = (
                    "cuda"
                    if self.compute_mode != "cpu" and torch.cuda.is_available()
                    else "cpu"
                )
                if ocr_device != last_reported_ocr_device:
                    last_reported_ocr_device = ocr_device
                    if self.compute_mode == "cuda" and ocr_device == "cpu":
                        self.messages.put(
                            ("status", "PyTorch без CUDA; OCR ограничен CPU-потоками профиля.")
                        )
                image = self._prepare_image(
                    image_bytes, width, height, self.max_ocr_dimension
                )
                language = self.selected_language
                visual_novel = self.translation_mode == "visual_novel"
                candidates = (language,)
                best_lines: list[tuple[str, float, int, int, int, int]] = []
                for code in candidates:
                    try:
                        if code not in readers or reader_devices.get(code) != ocr_device:
                            self.messages.put(
                                ("status", f"Загрузка OCR-модели {code} ({ocr_device.upper()})…")
                            )
                            readers[code] = Reader(
                                [code] if code == "en" else [code, "en"],
                                gpu=ocr_device == "cuda",
                                verbose=False,
                                **reader_options,
                            )
                            reader_devices[code] = ocr_device
                        results = readers[code].readtext(
                            image, detail=1, paragraph=False, batch_size=1
                        )
                    except Exception:
                        if ocr_device != "cuda":
                            raise
                        self.messages.put(
                            ("status", "CUDA OCR недоступен; переключаю OCR на CPU.")
                        )
                        ocr_device = "cpu"
                        last_reported_ocr_device = "cpu"
                        readers[code] = Reader(
                            [code] if code == "en" else [code, "en"],
                            gpu=False,
                            verbose=False,
                            **reader_options,
                        )
                        reader_devices[code] = "cpu"
                        results = readers[code].readtext(
                            image, detail=1, paragraph=False, batch_size=1
                        )
                    lines: list[tuple[str, float, int, int, int, int]] = []
                    for box, text, confidence in results:
                        text = text.strip()
                        if (
                            text
                            and confidence >= 0.12
                            and is_ocr_candidate(text)
                        ):
                            lines.append(
                                (
                                    text,
                                    float(confidence),
                                    int(min(point[1] for point in box)),
                                    int(min(point[0] for point in box)),
                                    int(max(point[1] for point in box)),
                                    int(max(point[0] for point in box)),
                                )
                            )
                    if code == "ja":
                        lines = remove_overlapping_ruby_readings(lines)
                    best_lines = lines
                best_lines.sort(key=lambda line: (line[2], line[3]))
                source_language = TRANSLATION_CODES[language]
                image_height, image_width = image.shape[:2]
                if self.follow_foreground:
                    best_lines = filter_bottom_navigation_lines(
                        best_lines,
                        image_height,
                    )
                scale_x = region["width"] / image_width
                scale_y = region["height"] / image_height
                lines_to_translate: list[dict[str, Any]] = []
                cjk_source = source_language == "ja"
                lines_to_translate_source = [
                    line
                    for line in group_ocr_lines(
                        best_lines,
                        paragraph_gap_ratio=1.25 if source_language == "ja" else 1.45,
                        horizontal_gap_ratio=8.0 if source_language == "ja" else 4.0,
                        separate_cjk_fragments=cjk_source,
                    )
                    if not is_low_value_game_text(line[0])
                ]
                for line_text, _confidence, y1, x1, y2, x2 in lines_to_translate_source:
                    left = region["left"] + int(x1 * scale_x)
                    top = region["top"] + int(y1 * scale_y)
                    right = region["left"] + int(x2 * scale_x)
                    bottom = region["top"] + int(y2 * scale_y)
                    lines_to_translate.append(
                        {
                            "text": line_text,
                            "language": source_language,
                            "bounds": {
                                "left": left,
                                "top": top,
                                "width": max(1, right - left),
                                "height": max(1, bottom - top),
                            },
                            "dialogue": visual_novel,
                        }
                    )
                if visual_novel and lines_to_translate:
                    lines_to_translate = [combine_dialogue_lines(lines_to_translate)]
                if self.context_reset_event.is_set():
                    context_buffer.reset()
                    self.context_reset_event.clear()
                context_buffer.observe(lines_to_translate, time.monotonic())
            except Exception as error:
                self.messages.put(("notice", f"Ошибка OCR: {error}"))

    def _translation_loop(self) -> None:
        """Устанавливает модели Argos и переводит локально на выбранном устройстве."""
        try:
            prepare_cuda_runtime()
            bundled_argos_models = application_directory() / "models" / "argos"
            if bundled_argos_models.is_dir():
                os.environ.setdefault(
                    "ARGOS_PACKAGES_DIR",
                    str(bundled_argos_models),
                )
            import ctranslate2
            import torch
            import argostranslate.package as argos_package
            import argostranslate.settings as argos_settings
            import argostranslate.translate as argos_translate
        except Exception as error:
            self.messages.put(("notice", f"Не удалось загрузить Argos Translate: {error}"))
            return

        cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        translation_models: dict[str, Any] = {}
        direct_translation_models: dict[tuple[str, str], Any] = {}
        available_packages: list[Any] | None = None
        active_mode: str | None = None
        active_device = "cpu"
        default_chunk_type = argos_settings.chunk_type
        installed_pairs = {
            (language.code, translation.to_lang.code)
            for language in argos_translate.get_installed_languages()
            for translation in language.translations_to
        }

        def get_translation_model(language: str) -> Any:
            nonlocal available_packages
            if language not in ARGOS_PATHS:
                raise ValueError(f"Неизвестный язык: {language}")
            missing_pairs = [
                pair for pair in ARGOS_PATHS[language] if pair not in installed_pairs
            ]
            if missing_pairs and available_packages is None:
                self.messages.put(("status", "Загрузка списка моделей перевода…"))
                argos_package.update_package_index()
                available_packages = argos_package.get_available_packages()
            for source_code, target_code in missing_pairs:
                model = next(
                    (
                        package
                        for package in available_packages or []
                        if package.from_code == source_code
                        and package.to_code == target_code
                    ),
                    None,
                )
                if model is None:
                    raise RuntimeError(f"Модель {source_code} → {target_code} не найдена")
                self.messages.put(
                    ("status", f"Загрузка модели {source_code} → {target_code}…")
                )
                install_argos_package(argos_package, model.download(), argos_translate)
                installed_pairs.add((source_code, target_code))

            if language not in translation_models:
                installed_languages = {
                    item.code: item for item in argos_translate.get_installed_languages()
                }
                source_lang = installed_languages.get(language)
                target_lang = installed_languages.get("ru")
                if source_lang is None or target_lang is None:
                    raise RuntimeError("Не удалось открыть языковые модели")
                translation = source_lang.get_translation(target_lang)
                if translation is None:
                    raise RuntimeError("Не найдена цепочка перевода на русский")
                translation_models[language] = translation
            return translation_models[language]

        def get_direct_translation_model(source: str, target: str) -> Any:
            key = (source, target)
            if key not in direct_translation_models:
                installed_languages = {
                    item.code: item for item in argos_translate.get_installed_languages()
                }
                source_lang = installed_languages.get(source)
                target_lang = installed_languages.get(target)
                if source_lang is None or target_lang is None:
                    raise RuntimeError("Не удалось открыть промежуточные языковые модели")
                translation = source_lang.get_translation(target_lang)
                if translation is None:
                    raise RuntimeError(f"Не найдена модель {source} → {target}")
                direct_translation_models[key] = translation
            return direct_translation_models[key]

        def translate_intermediate_english(text: str) -> str:
            nonlocal active_device
            get_translation_model("ja")
            try:
                return get_direct_translation_model("ja", "en").translate(text).strip()
            except Exception:
                if active_device != "cuda":
                    raise
                active_device = "cpu"
                argos_settings.device = "cpu"
                translation_models.clear()
                direct_translation_models.clear()
                argos_translate.get_installed_languages.cache_clear()
                get_translation_model("ja")
                translated = get_direct_translation_model("ja", "en").translate(text).strip()
                self.messages.put(
                    (
                        "status",
                        "CUDA недоступна; перевод продолжен на CPU. Для GPU см. README.md.",
                    )
                )
                return translated

        def prepare_translation_input(
            language: str,
            text: str,
            *,
            apply_first_person: bool,
        ) -> tuple[str, str]:
            if not apply_first_person:
                return language, text
            if language == "en":
                return language, to_first_person_en(text)
            if language == "ja":
                intermediate = translate_intermediate_english(text)
                return "en", to_first_person_en(intermediate)
            return language, text

        def translate_text(language: str, text: str) -> str:
            nonlocal active_device
            try:
                return get_translation_model(language).translate(text).strip()
            except Exception:
                if active_device != "cuda":
                    raise
                active_device = "cpu"
                argos_settings.device = "cpu"
                translation_models.clear()
                argos_translate.get_installed_languages.cache_clear()
                translated = get_translation_model(language).translate(text).strip()
                self.messages.put(
                    (
                        "status",
                        "CUDA недоступна; перевод продолжен на CPU. Для GPU см. README.md.",
                    )
                )
                return translated

        def translate_batch(language: str, texts: list[str]) -> list[str]:
            joined_text = "\n\n".join(texts)
            translated = translate_text(language, joined_text)
            parts = translated.split("\n\n")
            if len(parts) == len(texts):
                return [part.strip() for part in parts]
            self.messages.put(
                ("status", "Модель изменила разбиение строк; перевожу отдельно…")
            )
            return [translate_text(language, text) for text in texts]

        while not self.stop_event.is_set():
            try:
                lines = self.texts.get(timeout=0.3)
            except queue.Empty:
                continue

            # Если OCR успел распознать несколько кадров, переводим только самый новый.
            while True:
                try:
                    lines = self.texts.get_nowait()
                except queue.Empty:
                    break

            if self.compute_mode != active_mode:
                active_mode = self.compute_mode
                translation_models.clear()
                direct_translation_models.clear()
                has_cuda = active_mode != "cpu" and is_cuda_translation_available(
                    ctranslate2,
                    torch,
                )
                active_device = "cuda" if has_cuda else "cpu"
                argos_settings.device = active_device
                argos_settings.compute_type = "auto"
                argos_settings.chunk_type = (
                    argos_settings.ChunkType.MINISBD
                    if active_device == "cuda" and not torch.cuda.is_available()
                    else default_chunk_type
                )
                argos_translate.get_installed_languages.cache_clear()
                if active_mode == "cuda" and not has_cuda:
                    self.messages.put(
                        (
                            "status",
                            "CUDA недоступна в PyTorch; перевод будет выполняться на CPU.",
                        )
                    )
                elif active_mode == "auto" and not has_cuda:
                    self.messages.put(("status", "Авто: перевод выполняется на CPU."))
                else:
                    self.messages.put(
                        ("status", f"Перевод выполняется на {active_device.upper()}.")
                    )

            try:
                translated_by_key: dict[tuple[str, str], str] = {}
                missing_by_language: dict[str, dict[str, str]] = {}
                prepared_lines: list[
                    tuple[dict[str, Any], tuple[str, str], str, str]
                ] = []
                for item in lines:
                    apply_first_person = (
                        self.translation_mode == "visual_novel"
                        and self.first_person_enabled
                        and item.get("dialogue", False)
                    )
                    language, text = prepare_translation_input(
                        item["language"],
                        item["text"],
                        apply_first_person=apply_first_person,
                    )
                    key = (language, normalize_ocr_text(text))
                    prepared_lines.append((item, key, language, text))
                    if key in cache:
                        translated_by_key[key] = cache.pop(key)
                        cache[key] = translated_by_key[key]
                    else:
                        missing_by_language.setdefault(language, {}).setdefault(
                            key[1], text
                        )

                for language, pending in missing_by_language.items():
                    keys = [(language, normalized) for normalized in pending]
                    outputs = translate_batch(language, list(pending.values()))
                    for key, translated in zip(keys, outputs):
                        if not translated:
                            translated_by_key[key] = ""
                            cache[key] = ""
                            continue
                        translated_by_key[key] = translated
                        cache[key] = translated
                    while len(cache) > 300:
                        cache.popitem(last=False)

                translated_lines = []
                skipped_empty = 0
                for item, key, _, _ in prepared_lines:
                    translated = translated_by_key.get(key, "")
                    if not translated:
                        skipped_empty += 1
                        continue
                    translated_lines.append(
                        {
                            "text": translated,
                            "bounds": item["bounds"],
                            "dialogue": item.get("dialogue", False),
                        }
                    )
                self.messages.put(("translations", translated_lines))
                if skipped_empty:
                    self.messages.put(
                        (
                            "status",
                            f"Argos вернул пустой ответ для {skipped_empty} строк; остальные обработаны.",
                        )
                    )
            except Exception as error:
                detail = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
                self.messages.put(
                    ("notice", f"Перевод не выполнен: {detail[:110]}")
                )

    def _process_messages(self) -> None:
        """Все действия с Tkinter выполняются здесь, в главном потоке."""
        if self.stop_event.is_set():
            return
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "hotkey":
                if value == "select":
                    self.select_region()
                elif value == "pause":
                    self.toggle_pause()
                elif value == "exit":
                    self.close()
                    return
            elif kind == "translations":
                self.status_var.set(f"Переведено строк: {len(value)}.")
                self.overlay.show_translations(value)
            elif kind == "notice":
                self.status_var.set(value)
                self.overlay.show(value, self.region)
            elif kind == "status":
                self.status_var.set(value)
        self.overlay.check_pointer()
        self.root.after(100, self._process_messages)

    def close(self) -> None:
        """Останавливает потоки и удаляет глобальные горячие клавиши."""
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    enable_dpi_awareness()
    app = ScreenTranslator()
    app.run()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        packaged_self_test()
        raise SystemExit(0)
    main()

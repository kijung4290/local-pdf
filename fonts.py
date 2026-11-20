from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
import winreg

from fontTools import subset
from fontTools.ttLib import TTCollection, TTFont, TTLibError
import pymupdf as pdf


@dataclass(frozen=True)
class Face:
    label: str
    family: str
    style: str = ""
    path: Path | None = None
    index: int = -1
    aliases: tuple[str, ...] = ()


DEFAULT_FACE = Face("기본 고딕 · 한글 / 영문", "Malgun Gothic")


def font_paths():
    system = Path(os.environ["WINDIR"]) / "Fonts"
    user = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"
    paths = set()
    for directory in (system, user):
        if directory.is_dir():
            paths.update(directory.iterdir())
    for hive, folder in ((winreg.HKEY_LOCAL_MACHINE, system), (winreg.HKEY_CURRENT_USER, user)):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    _, value, _ = winreg.EnumValue(key, index)
                    if isinstance(value, str):
                        paths.add(folder / Path(os.path.expandvars(value)))
        except OSError:
            continue
    return sorted(path for path in paths if path.suffix.lower() in {".ttf", ".otf", ".ttc", ".otc"})


def read_face(font, path, index):
    if "OS/2" in font and font["OS/2"].fsType & 0x0202:
        return None
    if not any(table in font for table in ("glyf", "CFF ", "CFF2")):
        return None
    names = font["name"]
    family = names.getBestFamilyName() or path.stem
    style = names.getBestSubFamilyName() or "Regular"
    localized = next((names.getName(key, 3, encoding, 0x0412)
                      for key in (16, 1) for encoding in (1, 10)
                      if names.getName(key, 3, encoding, 0x0412)), None)
    label = localized.toUnicode() if localized else family
    if style.casefold() not in {"regular", "normal"}:
        label += f" · {style}"
    aliases = tuple(filter(None, (names.getDebugName(6), names.getBestFullName(), family)))
    return Face(label, family, style, path, index, aliases)


@lru_cache(maxsize=1)
def installed_faces():
    faces = {}
    for path in font_paths():
        try:
            if path.suffix.lower() in {".ttc", ".otc"}:
                with TTCollection(path, lazy=True) as collection:
                    for index, font in enumerate(collection.fonts):
                        face = read_face(font, path, index)
                        if face:
                            faces[face.label.casefold()] = face
            else:
                with TTFont(path, lazy=True) as font:
                    face = read_face(font, path, -1)
                    if face:
                        faces[face.label.casefold()] = face
        except (TTLibError, OSError, KeyError, UnicodeError, ValueError):
            continue
    return [DEFAULT_FACE, *sorted(faces.values(), key=lambda face: face.label.casefold())]


def matching_face(name):
    def normalize(text):
        return "".join(character for character in text.casefold() if character.isalnum())

    key = normalize(name.split("+", 1)[-1])
    for original, alternative in (("helvetica", "arial"), ("timesroman", "timesnewromanpsmt"),
                                  ("courier", "couriernew")):
        if key == original:
            key = alternative
            break
    if not key:
        return DEFAULT_FACE
    faces = installed_faces()
    for face in faces:
        if face.aliases and key == normalize(face.aliases[0]):
            return face
    return next((face for face in faces if key in map(normalize, face.aliases)), DEFAULT_FACE)


def add_face(path):
    with TTFont(path, lazy=True) as font:
        face = read_face(font, Path(path), -1)
    if face is None:
        raise ValueError("PDF에 포함할 수 있는 TrueType 또는 OpenType 글꼴을 선택하세요.")
    return face


@lru_cache(maxsize=1)
def default_buffer():
    return pdf.Font("cjk").buffer


def embedding_font(face, text):
    characters = set(text) - {"\n", "\r"}
    source = BytesIO(default_buffer()) if face.path is None else face.path
    with TTFont(source, fontNumber=face.index) as font:
        cmap = font.getBestCmap() or {}
        missing = sorted(char for char in characters if ord(char) not in cmap)
        if missing:
            sample = " ".join(repr(char) for char in missing[:8])
            raise ValueError(f"선택한 글꼴에 {sample} 문자가 없습니다. 다른 글꼴을 선택하세요.")
        flags = font["OS/2"].fsType if "OS/2" in font else 0
        if not flags & 0x0100:
            options = subset.Options(retain_gids=True)
            options.layout_features = []
            options.drop_tables += ["MERG", "meta"]
            worker = subset.Subsetter(options=options)
            worker.populate(text="".join(sorted(characters)))
            worker.subset(font)
        buffer = BytesIO()
        font.save(buffer)
    return pdf.Font(fontbuffer=buffer.getvalue())

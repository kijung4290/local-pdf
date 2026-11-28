from dataclasses import dataclass
import hashlib
from pathlib import Path
import math
import os
import re
import tempfile

import pymupdf as pdf

from fonts import embedding_font


pdf.TOOLS.set_small_glyph_heights(True)
HISTORY_BYTES = 128 * 1024 * 1024
HISTORY_STEPS = 12


@dataclass(frozen=True)
class TextLine:
    text: str
    rect: pdf.Rect
    marks: tuple[pdf.Rect, ...]
    origin: pdf.Point
    angle: float
    font: str
    size: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    revision: int
    page: int


class PasswordRequired(Exception):
    pass


@dataclass(frozen=True)
class Protection:
    user: str
    owner: str
    permissions: int = -4


def atomic_write(path, buffer, expected=None):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".localpdf-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(buffer)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None and Document.stamp(path) != expected:
            raise ValueError("파일이 다른 프로그램에서 변경되었습니다. 다른 이름으로 저장하세요.")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Document:
    def __init__(self, path=None, password="", data=None):
        self.path = Path(path).resolve() if path else None
        self.password = password
        self.file_stamp = self.stamp(self.path) if self.path else None
        self.pdf = self.open_bytes(self.path.read_bytes() if data is None else data)
        self.authorization = self.pdf.authenticate(password)
        self.past = []
        self.future = []
        self.revision = self.next_revision = 0
        self.saved_revision = 0 if self.path else -1

    @property
    def name(self):
        return self.path.name if self.path else "새 문서.pdf"

    @staticmethod
    def stamp(path):
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size, stat.st_ino
        except FileNotFoundError:
            return None

    def open_bytes(self, data):
        doc = pdf.open(stream=data, filetype="pdf")
        if not doc.is_pdf or doc.page_count == 0 and not doc.is_encrypted:
            doc.close()
            raise ValueError("페이지가 있는 PDF 파일을 선택하세요.")
        if not doc.authenticate(self.password):
            doc.close()
            raise PasswordRequired()
        if not doc.page_count:
            doc.close()
            raise ValueError("페이지가 있는 PDF 파일을 선택하세요.")
        return doc

    @property
    def dirty(self):
        return self.revision != self.saved_revision

    @property
    def protected(self):
        return self.pdf.xref_get_key(-1, "Encrypt")[0] != "null"

    @property
    def can_change_security(self):
        return not self.protected or bool(self.authorization & 4)

    def allowed(self, permission):
        return not self.protected or bool(self.authorization & 4 or self.pdf.permissions & permission)

    def authorize_owner(self, password):
        with pdf.open(stream=self.snapshot(0).data, filetype="pdf") as check:
            if not check.authenticate(password) & 4:
                return False
        self.authorization = self.pdf.authenticate(password)
        self.password = password
        return True

    def snapshot(self, page):
        buffer = self.pdf.tobytes(encryption=pdf.PDF_ENCRYPT_KEEP, deflate=True)
        return Snapshot(buffer, self.revision, page)

    def restore(self, snapshot):
        restored = self.open_bytes(snapshot.data)
        self.pdf.close()
        self.pdf = restored
        self.revision = snapshot.revision
        return snapshot.page

    def change(self, current_page, permission, update):
        if not self.allowed(permission):
            raise ValueError("이 PDF에 해당 작업을 할 권한이 없습니다.")
        previous = self.snapshot(current_page)
        try:
            update(self.pdf)
        except Exception:
            self.restore(previous)
            raise
        self.next_revision += 1
        self.revision = self.next_revision
        self.future.clear()
        self.past.append(previous)
        while len(self.past) > 1 and (len(self.past) > HISTORY_STEPS or
                                      sum(len(item.data) for item in self.past) > HISTORY_BYTES):
            self.past.pop(0)

    def step(self, current_page, redo=False):
        source, target = (self.future, self.past) if redo else (self.past, self.future)
        if not source:
            return current_page
        current = self.snapshot(current_page)
        page = self.restore(source[-1])
        source.pop()
        target.append(current)
        return page

    def save(self, path, security=None):
        path = Path(path).resolve()
        options = {"encryption": pdf.PDF_ENCRYPT_KEEP}
        password = self.password
        if security is not None:
            if not self.can_change_security:
                raise ValueError("암호를 변경하려면 소유자 암호로 PDF를 열어야 합니다.")
            protection = (Protection(security, security, self.pdf.permissions)
                          if isinstance(security, str) else security)
            password = protection.owner or protection.user
            if password:
                if any(len(item.encode("utf-8")) > 40 or "\0" in item for item in (protection.user, protection.owner)):
                    raise ValueError("암호는 UTF-8 기준 40바이트까지 입력하세요.")
                if protection.permissions != -4 and (not protection.owner or protection.owner == protection.user):
                    raise ValueError("권한을 제한할 때는 별도의 소유자 암호를 입력하세요.")
                options = dict(encryption=pdf.PDF_ENCRYPT_AES_256, owner_pw=password,
                               user_pw=protection.user, permissions=protection.permissions)
            else:
                options["encryption"] = pdf.PDF_ENCRYPT_NONE

        with self.open_bytes(self.snapshot(0).data) as copy:
            buffer = copy.tobytes(garbage=4, deflate=True, **options)
        with pdf.open(stream=buffer, filetype="pdf") as check:
            if security is not None and (bool(check.needs_pass) != bool(protection.user)
                    or (check.xref_get_key(-1, "Encrypt")[0] != "null") != bool(password)):
                raise ValueError("저장한 PDF의 암호 설정을 확인할 수 없습니다.")
            if (not check.authenticate(password) or check.page_count != self.pdf.page_count):
                raise ValueError("저장한 PDF를 다시 열어 확인할 수 없습니다.")
        atomic_write(path, buffer, self.file_stamp if path == self.path else None)

        if security is not None:
            self.password = password
            self.restore(Snapshot(buffer, self.revision, 0))
            self.authorization = self.pdf.authenticate(password)
            self.past.clear()
            self.future.clear()
        self.path = path
        self.file_stamp = self.stamp(path)
        self.saved_revision = self.revision

    def extract(self, indices, path):
        if self.path and Path(path).resolve() == self.path:
            raise ValueError("추출할 페이지를 새 파일 이름으로 저장하세요.")
        self.check_extract_permission()
        self.write_extract(self.snapshot(0).data, indices, path)

    def split(self, folder, pages_per_file):
        self.check_extract_permission()
        count = self.pdf.page_count
        if not 1 <= pages_per_file < count:
            raise ValueError("파일당 페이지 수를 전체 페이지 수보다 작게 입력하세요.")
        stem = Path(self.name).stem
        output = Path(folder) / f"{stem}_분할"
        if output.exists():
            raise FileExistsError(f"‘{output.name}’ 폴더가 이미 있습니다. 다른 저장 위치를 선택하세요.")
        source = self.snapshot(0).data
        width = max(3, len(str(count)))
        paths = []
        with tempfile.TemporaryDirectory(prefix=".localpdf-", dir=folder) as temporary:
            staging = Path(temporary) / "pages"
            staging.mkdir()
            for first in range(0, count, pages_per_file):
                last = min(first + pages_per_file, count)
                name = f"{stem}_{first + 1:0{width}}-{last:0{width}}.pdf"
                self.write_extract(source, list(range(first, last)), staging / name)
                paths.append(output / name)
            staging.rename(output)
        return paths

    def check_extract_permission(self):
        if not self.allowed(pdf.PDF_PERM_COPY) or not self.allowed(pdf.PDF_PERM_ASSEMBLE):
            raise ValueError("이 PDF의 페이지를 추출할 권한이 없습니다.")

    def write_extract(self, source, indices, path):
        with self.open_bytes(source) as copy:
            copy.select(indices)
            for name in copy.embfile_names():
                copy.embfile_del(name)
            buffer = copy.tobytes(garbage=4, deflate=True, encryption=pdf.PDF_ENCRYPT_KEEP)
        atomic_write(path, buffer)

    def copy_pages(self, indices):
        if not self.allowed(pdf.PDF_PERM_COPY) or not self.allowed(pdf.PDF_PERM_ASSEMBLE):
            raise ValueError("이 PDF의 페이지를 복사할 권한이 없습니다.")
        if not indices or any(index < 0 or index >= self.pdf.page_count for index in indices):
            raise ValueError("복사할 페이지를 선택하세요.")
        indices = sorted(set(indices))
        ranges = []
        first = previous = indices[0]
        for index in indices[1:]:
            if index != previous + 1:
                ranges.append((first, previous))
                first = index
            previous = index
        ranges.append((first, previous))
        with pdf.open() as fragment:
            for number, (first, last) in enumerate(ranges):
                fragment.insert_pdf(self.pdf, from_page=first, to_page=last, final=number == len(ranges) - 1)
            if len(ranges) > 1:
                self.copy_links_between_ranges(fragment, indices, ranges)
            return fragment.tobytes(garbage=4, deflate=True)

    def copy_links_between_ranges(self, fragment, indices, ranges):
        destination = {original: new for new, original in enumerate(indices)}
        # insert_pdf retains links within the range being copied. Restore links between selected ranges.
        for first, last in ranges:
            for index in range(first, last + 1):
                original = self.pdf[index]
                page = fragment[destination[index]]
                for link in original.get_links():
                    target = link.get("page")
                    if link["kind"] != pdf.LINK_GOTO or target not in destination or first <= target <= last:
                        continue
                    page.insert_link({"kind": pdf.LINK_GOTO, "page": destination[target],
                                      "from": link["from"] * original.derotation_matrix,
                                      "to": link["to"] * self.pdf[target].derotation_matrix,
                                      "zoom": link.get("zoom", 0)})


def organize_pages(doc, plan):
    original = list(range(doc.page_count))
    indices = [index for index, _ in plan]
    if not indices or len(set(indices)) != len(indices) or any(index not in range(doc.page_count) for index in indices):
        raise ValueError("유효한 페이지를 하나 이상 남겨야 합니다.")
    if indices != original:
        doc.select(indices)
    for index, (_, rotation) in enumerate(plan):
        if rotation:
            page = doc[index]
            page.set_rotation(page.rotation + rotation)


def page_indices(value, count):
    if not value.strip():
        return list(range(count))
    indices = {}
    for value in value.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:[-–]\s*([0-9]+)\s*)?", value)
        if match is None:
            raise ValueError("페이지를 1, 3-5 형식으로 입력하세요.")
        start = int(match[1])
        end = int(match[2]) if match[2] else start
        if not 1 <= start <= end <= count:
            raise ValueError(f"1~{count}페이지 사이에서 낮은 번호부터 입력하세요.")
        indices.update((index, None) for index in range(start - 1, end))
    return list(indices)


def text_lines(page):
    for block in page.get_text("rawdict", flags=pdf.TEXTFLAGS_RAWDICT & ~pdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        for line in block.get("lines", []):
            spans = [span for span in line["spans"] if span["chars"]]
            if not spans:
                continue
            chars = [char for span in spans for char in span["chars"]]
            text = "".join(char["c"] for char in chars)
            if not text.strip():
                continue
            marks = []
            for char in chars:
                rect = pdf.Rect(char["bbox"])
                if not rect.is_empty:
                    x, y = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
                    dx, dy = rect.width * .12, rect.height * .12
                    marks.append(pdf.Rect(x - dx, y - dy, x + dx, y + dy))
            first = spans[0]
            angle = math.degrees(math.atan2(-line["dir"][1], line["dir"][0]))
            yield TextLine(text, pdf.Rect(line["bbox"]), tuple(marks), pdf.Point(first["origin"]),
                           angle % 360, first["font"], first["size"], pdf.sRGB_to_pdf(first["color"]))


def check_pending_redactions(page):
    if next(page.annots(types=[pdf.PDF_ANNOT_REDACT]), None) is not None:
        raise ValueError("이 페이지에 기존 삭제 표시가 있습니다. 표시를 적용하거나 지운 뒤 편집하세요.")


def rotated_vectors(angle):
    axes = {0: ((1, 0), (0, 1)), 90: ((0, -1), (1, 0)),
            180: ((-1, 0), (0, -1)), 270: ((0, 1), (-1, 0))}
    return tuple(pdf.Point(*axis) for axis in axes[angle])


def write_text(page, point, text, face, size, color, line=None):
    text = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    if not text.strip() and line is None:
        raise ValueError("삽입할 텍스트를 입력하세요.")
    if line is not None:
        check_pending_redactions(page)
        angle = round(line.angle / 90) * 90 % 360
        if not math.isclose(angle, line.angle, abs_tol=.5) and line.angle < 359.5:
            raise ValueError("기울어진 텍스트는 영역 삭제 후 새 텍스트를 삽입하세요.")
    else:
        angle = page.rotation

    placements = []
    if text.strip():
        font = embedding_font(face, text)
        advance, down = rotated_vectors(angle)
        ascent = min(1.2, max(.7, font.ascender)) * size
        descent = min(.55, max(.15, -font.descender)) * size
        baseline = line.origin if line else point + down * ascent
        bounds = page.rect * page.derotation_matrix
        for index, row in enumerate(text.split("\n")):
            if not row.strip():
                continue
            start = baseline + down * max(size * 1.2, ascent + descent) * index
            end = start + advance * font.text_length(row.rstrip(), fontsize=size)
            limits = pdf.Rect(bounds.x0 - .5, bounds.y0 - .5, bounds.x1 + .5, bounds.y1 + .5)
            if not all(limits.contains(point) for point in (start - down * ascent, end + down * descent)):
                raise ValueError("텍스트가 페이지 가장자리를 넘습니다. 글자 크기를 줄이거나 줄을 나누세요.")
            placements.append((start, row.rstrip()))

    if line is not None:
        for mark in line.marks:
            page.add_redact_annot(mark, fill=False, cross_out=False)
        page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE, graphics=pdf.PDF_REDACT_LINE_ART_NONE)
    if placements:
        buffer = font.buffer
        name = "Local" + hashlib.sha256(buffer).hexdigest()[:20]
        page.insert_font(fontname=name, fontbuffer=buffer)
        for start, row in placements:
            if page.insert_text(start, row, fontname=name, fontsize=size, color=color, rotate=angle) != 1:
                raise ValueError("이 위치에 텍스트를 넣을 수 없습니다. 페이지 가장자리에서 조금 이동하세요.")


def redact_area(page, rect, black=False):
    check_pending_redactions(page)
    for annot in list(page.annots() or []):
        if annot.rect.intersects(rect):
            page.delete_annot(annot)
    for widget in list(page.widgets() or []):
        if widget.rect.intersects(rect):
            page.delete_widget(widget)
    fill = (0, 0, 0) if black else (1, 1, 1)
    page.add_redact_annot(rect, fill=fill, cross_out=False)
    page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=pdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)


def add_markup(page, mode, bounds, color):
    methods = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
               "strike": page.add_strikeout_annot}
    quads = []
    for block in page.get_text("dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                hit = pdf.Rect(span["bbox"]) & bounds
                if hit.is_empty:
                    continue
                if abs(line["dir"][1]) < .01:
                    hit.y0, hit.y1 = span["bbox"][1], span["bbox"][3]
                    quads.append(hit.quad)
                else:
                    quads.append(pdf.recover_quad(line["dir"], span))
    if not quads:
        raise ValueError("선택 영역에서 텍스트를 찾지 못했습니다.")
    annot = methods[mode](quads)
    annot.set_colors(stroke=color)
    annot.update()


def mark_page(page, text, face, size, opacity, at_bottom=False, font=None):
    font = font or embedding_font(face, text)
    visual = page.rect
    measured = font.text_length(text, fontsize=size)
    if measured > visual.width - 36:
        size *= (visual.width - 36) / measured
        measured = font.text_length(text, fontsize=size)
    if size < 3 or visual.height < size + 12:
        raise ValueError("페이지나 표시할 영역이 너무 작습니다. 문구를 줄이세요.")
    baseline = visual.height - max(12, size) if at_bottom else (visual.height + size * .65) / 2
    point = pdf.Point((visual.width - measured) / 2, baseline) * page.derotation_matrix
    buffer = font.buffer
    name = "Local" + hashlib.sha256(buffer).hexdigest()[:20]
    page.insert_font(fontname=name, fontbuffer=buffer)
    page.insert_text(point, text, fontname=name, fontsize=size, rotate=page.rotation,
                     fill_opacity=opacity, color=(.20, .25, .35))


def document_from_images(images):
    with pdf.open() as doc:
        for image in images:
            pix = pdf.Pixmap(image)
            scale = min(1, 842 / max(pix.width, pix.height))
            page = doc.new_page(width=pix.width * scale, height=pix.height * scale)
            page.insert_image(page.rect, stream=image)
        return Document(data=doc.tobytes(deflate=True))

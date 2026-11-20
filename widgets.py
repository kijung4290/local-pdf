from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt, Signal, QStringListModel
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)
import pymupdf as pdf

from fonts import add_face, installed_faces, matching_face
from pdf_core import Protection, page_indices


IMAGE_FILTER = "이미지 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"


def image_bytes(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(f"이미지를 열 수 없습니다. {reader.errorString()}")
    result = QByteArray()
    buffer = QBuffer(result)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise ValueError("이미지를 변환할 수 없습니다.")
    return bytes(result)


def page_image(page, scale, annotations=True):
    pixmap = page.get_pixmap(matrix=pdf.Matrix(scale, scale), colorspace=pdf.csRGB, alpha=False, annots=annotations)
    return QImage(pixmap.samples_mv, pixmap.width, pixmap.height, pixmap.stride,
                  QImage.Format.Format_RGB888).copy()


class PageView(QGraphicsView):
    selected = Signal(str, object)
    zoomed = Signal(int)
    margin = 32
    click_tools = {"insert", "memo", "read_note", "erase_note"}

    def __init__(self):
        self.canvas = QGraphicsScene()
        super().__init__(self.canvas)
        self.setObjectName("pageView")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.paper = QRectF()
        self.scale = 1.0
        self.mode = "hand"
        self.start = self.rubber = self.hover = None
        self.ink_points = []
        self.ink_color = QColor("#356be7")
        self.highlights = []
        self.lines = []
        self.rotation = pdf.Matrix(1, 1)
        self.unrotate = pdf.Matrix(1, 1)
        self.set_mode("hand")

    def set_mode(self, mode):
        self.mode = mode
        self.clear_mark("hover")
        self.clear_mark("rubber")
        self.start = None
        self.setDragMode(self.DragMode.ScrollHandDrag if mode == "hand" else self.DragMode.NoDrag)
        cursors = {"hand": Qt.CursorShape.OpenHandCursor, "edit": Qt.CursorShape.IBeamCursor}
        self.viewport().setCursor(cursors.get(mode, Qt.CursorShape.CrossCursor))

    def clear_mark(self, name):
        mark = getattr(self, name)
        if mark is not None:
            self.canvas.removeItem(mark)
            setattr(self, name, None)

    def show_page(self, page, scale, keep_position=False):
        midpoint = self.mapToScene(self.viewport().rect().center()) / self.scale
        limited = min(scale * max(self.devicePixelRatioF(), 1),
                      4500 / max(page.rect.width, page.rect.height))
        image = page_image(page, limited)
        self.rubber = self.hover = self.start = None
        self.highlights.clear()
        self.canvas.clear()
        self.lines = []
        self.scale = scale
        self.rotation = page.rotation_matrix
        self.unrotate = page.derotation_matrix
        self.paper = QRectF(0, 0, page.rect.width * scale, page.rect.height * scale)
        self.canvas.setSceneRect(self.paper.adjusted(-self.margin, -self.margin, self.margin, self.margin))
        self.canvas.addRect(self.paper.adjusted(-2, -1, 3, 6), Qt.PenStyle.NoPen, QColor(32, 42, 63, 12))
        self.canvas.addRect(self.paper.translated(1, 3), Qt.PenStyle.NoPen, QColor(32, 42, 63, 26))
        paper = self.canvas.addPixmap(QPixmap.fromImage(image))
        paper.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        paper.setTransform(paper.transform().scale(self.paper.width() / image.width(),
                                                    self.paper.height() / image.height()))
        self.centerOn(midpoint * scale if keep_position else QPointF(self.paper.center().x(), 0))

    def scene_rect(self, rect):
        rotated = rect * self.rotation
        return QRectF(rotated.x0 * self.scale, rotated.y0 * self.scale,
                      rotated.width * self.scale, rotated.height * self.scale)

    def pdf_point(self, point):
        return pdf.Point(point.x() / self.scale, point.y() / self.scale) * self.unrotate

    def draw_box(self, rect, border, fill):
        pen = QPen(QColor(border))
        pen.setCosmetic(True)
        box = self.canvas.addRect(rect, pen, QColor(*fill))
        box.setZValue(5)
        return box

    def search_marks(self, hits, active=None):
        for item in self.highlights:
            self.canvas.removeItem(item)
        self.highlights.clear()
        for index, hit in enumerate(hits):
            rect = self.scene_rect(hit)
            current = index == active
            self.highlights.append(self.draw_box(rect, "#dc751d" if current else "#d8aa46",
                                                 (255, 176, 60, 130 if current else 55)))
            if current:
                self.ensureVisible(rect, 40, 48)

    def line_at(self, point):
        def distance(item):
            rect = self.scene_rect(item.rect)
            return abs(point.y() - rect.center().y()) + abs(point.x() - rect.center().x()) * .08

        return min((line for line in self.lines if self.scene_rect(line.rect).adjusted(-3, -3, 3, 3).contains(point)),
                   key=distance, default=None)

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self.mode == "hand" or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
        elif self.paper.contains(point):
            self.start = point
            self.ink_points = [point] if self.mode == "ink" else []
            event.accept()

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self.mode == "edit":
            self.clear_mark("hover")
            line = self.line_at(point)
            if line:
                self.hover = self.draw_box(self.scene_rect(line.rect), "#346ce0", (57, 109, 225, 37))
        elif self.start is not None and self.mode == "ink":
            point = QPointF(min(max(point.x(), self.paper.left()), self.paper.right()),
                            min(max(point.y(), self.paper.top()), self.paper.bottom()))
            previous = self.ink_points[-1]
            if (point - previous).manhattanLength() >= 1.5:
                self.ink_points.append(point)
                path = QPainterPath(self.ink_points[0])
                for dot in self.ink_points[1:]:
                    path.lineTo(dot)
                if self.rubber is None:
                    pen = QPen(self.ink_color, max(1.4, 2 * self.scale))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    self.rubber = self.canvas.addPath(path, pen)
                    self.rubber.setZValue(5)
                else:
                    self.rubber.setPath(path)
        elif self.start is not None and self.mode not in self.click_tools:
            self.clear_mark("rubber")
            area = QRectF(self.start, point).normalized().intersected(self.paper)
            color = "#b65645" if self.mode == "redact" else "#346ce0"
            fill = (213, 96, 75, 55) if self.mode == "redact" else (57, 109, 225, 45)
            self.rubber = self.draw_box(area, color, fill)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        start, self.start = self.start, None
        point = self.mapToScene(event.position().toPoint())
        if self.mode == "edit":
            self.selected.emit(self.mode, self.line_at(point))
        elif self.mode == "ink":
            if len(self.ink_points) > 1:
                self.selected.emit(self.mode, [self.pdf_point(dot) for dot in self.ink_points])
            self.ink_points.clear()
        elif self.mode in self.click_tools and self.paper.contains(point):
            self.selected.emit(self.mode, self.pdf_point(point))
        else:
            area = QRectF(start, point).normalized().intersected(self.paper)
            if area.width() >= 3 and area.height() >= 3:
                selection = pdf.Rect(self.pdf_point(area.topLeft()), self.pdf_point(area.bottomRight())).normalize()
                self.selected.emit(self.mode, selection)
        self.clear_mark("rubber")

    def leaveEvent(self, event):
        self.clear_mark("hover")
        super().leaveEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and steps:
            self.zoomed.emit(1 if steps > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)


def dialog_buttons(dialog, label, callback):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(label)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
    buttons.accepted.connect(callback)
    buttons.rejected.connect(dialog.reject)
    return buttons


class TextDialog(QDialog):
    def __init__(self, parent, line=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("텍스트 수정" if line else "텍스트 삽입")
        self.setMinimumWidth(485)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.text = QPlainTextEdit(line.text if line else "")
        self.text.setPlaceholderText("PDF에 넣을 텍스트를 입력하세요")
        self.text.setFixedHeight(138)
        layout.addWidget(self.text)
        self.fonts = QComboBox()
        self.fonts.setEditable(True)
        self.fonts.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        faces = installed_faces()
        self.labels = QStringListModel(self)
        for face in faces:
            self.fonts.addItem(face.label, face)
        self.update_completions()
        font_controls = QHBoxLayout()
        font_controls.addWidget(self.fonts, 1)
        import_button = QPushButton("글꼴 파일…")
        import_button.clicked.connect(self.import_font)
        font_controls.addWidget(import_button)
        form.addRow("글꼴", font_controls)
        self.size = QDoubleSpinBox()
        self.size.setRange(1, 300)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.color = QPushButton()
        self.color.clicked.connect(self.choose_color)
        color = QColor.fromRgbF(*line.color) if line else QColor("#222b33")
        form.addRow("크기", self.size)
        form.addRow("색상", self.color)
        layout.addLayout(form)
        self.hint = QLabel("텍스트를 비워 적용하면 선택한 줄을 삭제합니다." if line else
                           "선택한 글꼴을 PDF에 포함해 다른 PC에서도 같은 모양으로 표시합니다.")
        self.hint.setProperty("muted", True)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.result_values = None
        layout.addWidget(dialog_buttons(self, "적용", self.validate))
        face = matching_face(line.font) if line else faces[0]
        size = line.size if line else 13
        if not line and settings:
            face, size, color = settings
            if self.fonts.findData(face) < 0:
                self.fonts.addItem(face.label, face)
                self.update_completions()
        self.fonts.setCurrentIndex(self.fonts.findData(face))
        self.size.setValue(size)
        self.set_color(color)
        self.fonts.currentTextChanged.connect(self.update_font)
        self.size.valueChanged.connect(self.update_font)
        self.update_font()
        self.text.setFocus()
        self.text.selectAll()

    def update_completions(self):
        # Keep the completer separate from the combo model so searching can match any part of a family name.
        self.labels.setStringList([self.fonts.itemText(index) for index in range(self.fonts.count())])
        if not hasattr(self, "completer"):
            self.completer = QCompleter(self.labels, self)
            self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.fonts.setCompleter(self.completer)

    def find_face(self):
        text = self.fonts.currentText().strip().casefold()
        for index in range(self.fonts.count()):
            if self.fonts.itemText(index).casefold() == text:
                return self.fonts.itemData(index)
        return None

    def update_font(self, *_):
        face = self.find_face()
        if face:
            font = QFont(face.family)
            font.setPointSizeF(self.size.value())
            if face.style:
                font.setStyleName(face.style)
            self.text.setFont(font)

    def import_font(self):
        path, _ = QFileDialog.getOpenFileName(self, "글꼴 파일 선택", "", "OpenType / TrueType (*.otf *.ttf)")
        if path:
            try:
                face = add_face(path)
                QFontDatabase.addApplicationFont(path)
                existing = self.fonts.findData(face)
                if existing < 0:
                    label = face.label
                    while self.fonts.findText(label) >= 0:
                        label += " · 파일"
                    self.fonts.addItem(label, face)
                    self.update_completions()
                    existing = self.fonts.count() - 1
                self.fonts.setCurrentIndex(existing)
            except Exception as error:
                QMessageBox.warning(self, "글꼴 파일", str(error))

    def set_color(self, color):
        self.chosen = color
        self.color.setText(color.name().upper())
        self.color.setStyleSheet(f"background-color: {color.name()}; color: " +
                                 ("white;" if color.lightness() < 130 else "#101b23;"))

    def choose_color(self):
        color = QColorDialog.getColor(self.chosen, self, "텍스트 색상")
        if color.isValid():
            self.set_color(color)

    def validate(self):
        face = self.find_face()
        if face is None:
            QMessageBox.warning(self, "글꼴 선택", "목록에서 사용할 글꼴을 선택하세요.")
            return
        self.result_values = self.text.toPlainText(), face, self.size.value(), self.chosen
        self.accept()


class PasswordDialog(QDialog):
    def __init__(self, parent, protected, permissions=-4):
        super().__init__(parent)
        self.setWindowTitle("PDF 암호 보호")
        self.setMinimumWidth(475)
        layout = QVBoxLayout(self)
        self.hint = QLabel("열기 암호와 소유자 암호를 설정합니다. 소유자 암호를 별도로 설정하면 사용 권한을 제한할 수 있습니다.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        form = QFormLayout()
        self.first, self.second, self.owner, self.owner_confirm = (QLineEdit() for _ in range(4))
        for box in (self.first, self.second, self.owner, self.owner_confirm):
            box.setEchoMode(QLineEdit.EchoMode.Password)
            box.setMaxLength(40)
        form.addRow("열기 암호", self.first)
        form.addRow("열기 암호 확인", self.second)
        form.addRow("소유자 암호", self.owner)
        form.addRow("소유자 암호 확인", self.owner_confirm)
        layout.addLayout(form)
        self.permits = []
        for text, flag in (("편집·페이지 구성 허용", pdf.PDF_PERM_MODIFY | pdf.PDF_PERM_ASSEMBLE | pdf.PDF_PERM_FORM),
                           ("복사·추출 허용", pdf.PDF_PERM_COPY),
                           ("인쇄 허용", pdf.PDF_PERM_PRINT | pdf.PDF_PERM_PRINT_HQ),
                           ("주석 허용", pdf.PDF_PERM_ANNOTATE)):
            control = QCheckBox(text)
            control.setChecked((permissions & flag) == flag)
            self.permits.append((control, flag))
            layout.addWidget(control)
        self.remove = QCheckBox("저장본에서 암호 보호 해제")
        self.remove.setVisible(protected)
        self.remove.toggled.connect(self.toggle_remove)
        layout.addWidget(self.remove)
        layout.addWidget(dialog_buttons(self, "저장 위치 선택", self.validate))

    def toggle_remove(self, remove):
        for control in (self.first, self.second, self.owner, self.owner_confirm,
                        *(item[0] for item in self.permits)):
            control.setDisabled(remove)

    def validate(self):
        user, owner = self.first.text(), self.owner.text()
        permissions = -4
        for control, flag in self.permits:
            if not control.isChecked():
                permissions &= ~flag
        if self.remove.isChecked():
            user = owner = ""
        elif not user.strip() and not owner.strip() or any(len(item.encode("utf-8")) > 40 for item in (user, owner)):
            QMessageBox.warning(self, "암호 입력", "열기 또는 소유자 암호를 UTF-8 기준 1~40바이트로 입력하세요.")
            return
        elif user != self.second.text() or owner != self.owner_confirm.text():
            QMessageBox.warning(self, "암호 확인", "암호와 확인 값이 일치해야 합니다.")
            return
        elif permissions != -4 and (not owner or user == owner):
            QMessageBox.warning(self, "소유자 암호", "권한을 제한하려면 별도의 소유자 암호를 입력하세요.")
            return
        self.protection = Protection(user, owner, permissions)
        self.accept()


class PagesDialog(QDialog):
    def __init__(self, parent, count, current, operation):
        super().__init__(parent)
        self.count = count
        self.operation = operation
        title = {"export": "내보내기", "watermark": "워터마크", "number": "쪽 번호"}[operation]
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.range = QLineEdit(str(current) if operation == "export" else "")
        self.range.setPlaceholderText(f"비워 두면 전체 · 1~{count}페이지")
        form.addRow("페이지 범위", self.range)
        if operation == "export":
            self.kind = QComboBox()
            for description, kind in (("PDF · 선택 페이지를 한 파일로", "pdf"),
                                      ("PNG · 페이지 이미지", "png"), ("JPEG · 페이지 이미지", "jpg"),
                                      ("TXT · 선택 페이지의 텍스트", "txt")):
                self.kind.addItem(description, kind)
            form.addRow("파일 형식", self.kind)
            self.dpi = QSpinBox()
            self.dpi.setRange(72, 300)
            self.dpi.setValue(144)
            self.dpi.setSuffix(" dpi")
            form.addRow("이미지 해상도", self.dpi)
            self.dpi.setEnabled(False)
            self.kind.currentIndexChanged.connect(lambda: self.dpi.setEnabled(self.kind.currentData() in {"png", "jpg"}))
        elif operation == "watermark":
            self.text = QLineEdit()
            self.text.setPlaceholderText("예시: 검토용")
            self.text.setMaxLength(120)
            form.addRow("문구", self.text)
            self.size = QSpinBox()
            self.size.setRange(12, 130)
            self.size.setValue(42)
            self.size.setSuffix(" pt")
            form.addRow("크기", self.size)
            self.opacity = QSpinBox()
            self.opacity.setRange(5, 100)
            self.opacity.setValue(22)
            self.opacity.setSuffix(" %")
            form.addRow("불투명도", self.opacity)
        else:
            self.first = QSpinBox()
            self.first.setRange(1, 1000000)
            form.addRow("시작 번호", self.first)
        outer.addLayout(form)
        hint = QLabel("페이지 범위는 1, 3-5처럼 입력할 수 있습니다.")
        hint.setProperty("muted", True)
        outer.addWidget(hint)
        outer.addWidget(dialog_buttons(self, "저장 위치 선택" if operation == "export" else "적용", self.validate))

    def validate(self):
        try:
            self.indices = page_indices(self.range.text(), self.count)
            if self.operation == "watermark" and not self.text.text().strip():
                raise ValueError("워터마크 문구를 입력하세요.")
        except ValueError as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))
            return
        self.accept()

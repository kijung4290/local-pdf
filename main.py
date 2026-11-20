from dataclasses import dataclass
from pathlib import Path
import os
import sys
from urllib.parse import quote

from PySide6.QtCore import QDir, QMimeData, QPointF, QSignalBlocker, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QTabBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)
import pymupdf as pdf

from fonts import DEFAULT_FACE, embedding_font
from pdf_core import (Document, PasswordRequired, add_markup, atomic_write, document_from_images,
                      mark_page, redact_area, text_lines, write_text)
from updates import Updates
from widgets import IMAGE_FILTER, PageView, PagesDialog, PasswordDialog, TextDialog, image_bytes, page_image


APP = "로컬 PDF"
VERSION = "1.2.0"
ROOT = Path(__file__).resolve().parent
PAGE_CLIPBOARD = "application/vnd.localpdf.pages+pdf"
MODES = {
    "hand": ("보기", "페이지를 드래그해 이동합니다. Ctrl+휠로 확대하거나 축소할 수 있습니다."),
    "edit": ("텍스트 수정", "바꿀 텍스트 줄을 클릭하세요."),
    "insert": ("텍스트 삽입", "새 텍스트를 넣을 위치를 클릭하세요."),
    "redact": ("영역 삭제", "내용을 제거할 영역을 드래그하세요."),
    "highlight": ("형광펜", "강조할 텍스트를 드래그하세요."),
    "copy": ("텍스트 복사", "복사할 글자를 드래그하세요. 선택한 텍스트가 클립보드에 저장됩니다."),
    "image": ("이미지·도장 삽입", "이미지나 도장을 놓을 영역을 드래그하세요."),
    "memo": ("메모 추가", "메모를 붙일 위치를 클릭하세요."),
    "read_note": ("메모 열기·수정", "페이지의 메모 아이콘을 클릭하세요."),
    "underline": ("밑줄", "밑줄을 넣을 텍스트를 드래그하세요."),
    "strike": ("취소선", "취소선을 넣을 텍스트를 드래그하세요."),
    "ink": ("펜 그리기", "페이지에 마우스로 그리세요."),
    "rectangle": ("사각형 주석", "사각형으로 표시할 영역을 드래그하세요."),
    "erase_note": ("주석 지우기", "지울 주석을 클릭하세요."),
    "crop": ("페이지 자르기", "페이지에서 보이게 할 영역을 드래그하세요."),
}

GROUPS = (
    ("편집", ("hand", "edit", "insert", "image", "redact", "copy"), ("watermark", "numbers", "security")),
    ("주석", ("highlight", "underline", "strike", "memo", "read_note", "ink", "rectangle", "erase_note"), ()),
    ("페이지", ("crop",), ("copy_pages", "paste_pages", "rotate", "blank", "duplicate", "move_up", "move_down", "delete", "append", "presentation")),
    ("파일", (), ("export", "from_images", "print", "saveas", "default")),
)


ICON_LINES = {
    "hand": [((3,8),(3,3),(8,3)), ((12,3),(17,3),(17,8)), ((17,12),(17,17),(12,17)), ((8,17),(3,17),(3,12))],
    "edit": [((3,4),(12,4)), ((7.5,4),(7.5,16)), ((4,16),(11,16)), ((14,9),(17,12),(13,16))],
    "insert": [((3,4),(12,4)), ((7.5,4),(7.5,16)), ((13,11),(19,11)), ((16,8),(16,14))],
    "image": [((3,4),(17,4),(17,16),(3,16),(3,4)), ((4,13),(8,9),(11,12),(13,10),(17,14))],
    "redact": [((3,12),(10,4),(17,10),(11,17),(7,17),(3,12)), ((8,7),(14,13)), ((11,17),(18,17))],
    "copy": [((7,7),(17,7),(17,17),(7,17),(7,7)), ((3,13),(3,3),(13,3))],
    "highlight": [((5,12),(12,5),(16,9),(9,16),(5,16),(5,12)), ((3,18),(12,18))],
    "underline": [((5,13),(10,4),(15,13)), ((7,10),(13,10)), ((4,17),(16,17))],
    "strike": [((5,14),(10,4),(15,14)), ((3,10),(17,10))],
    "memo": [((3,4),(17,4),(17,14),(9,14),(5,17),(5,14),(3,14),(3,4)), ((7,8),(13,8)), ((7,11),(11,11))],
    "ink": [((3,15),(5,11),(8,8),(9,9),(7,14),(9,15),(13,10),(16,11),(18,9))],
    "rectangle": [((3,5),(17,5),(17,15),(3,15),(3,5))],
    "erase_note": [((5,6),(15,6)), ((7,6),(7,16),(13,16),(13,6)), ((8,4),(12,4))],
    "crop": [((5,3),(5,15),(17,15)), ((3,5),(15,5),(15,17))],
}
ICON_LINES["read_note"] = ICON_LINES["memo"]


def tool_icon(key):
    icon = QIcon()
    for mode, color in ((QIcon.Mode.Normal, "#526784"), (QIcon.Mode.Disabled, "#a0aabd")):
        raster = QPixmap(40, 40)
        raster.fill(Qt.GlobalColor.transparent)
        painter = QPainter(raster)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for stroke in ICON_LINES[key]:
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in stroke]))
        painter.end()
        raster.setDevicePixelRatio(2)
        icon.addPixmap(raster, mode)
    return icon


def label(text, name="", muted=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setProperty("muted", muted)
    return widget


def panel(name, margins, spacing):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return widget, layout


@dataclass
class DocumentTab:
    document: Document
    page: int = 0
    zoom: str | float = "page"
    mode: str = "hand"
    group: int = 0
    navigation: int = 0
    selected_pages: tuple[int, ...] = ()
    scroll_position: QPointF | None = None
    query: str = ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = None
        self.active_tab = None
        self.page_index = 0
        self.zoom = "page"
        self.last_text_settings = None
        self.search_hits = []
        self.search_page = self.search_index = 0
        self.search_term = ""
        self.page_lines = None
        self.annotation_color = QColor("#346ce0")
        self.presentation_state = None
        self.closing_for_update = False
        self.setMinimumSize(1030, 680)
        self.resize(1360, 865)
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(ROOT / "assets/app.ico")))
        self.actions = {}
        self.setup_actions()
        self.setup_ui()
        self.search_timer = QTimer(self, interval=12)
        self.search_timer.timeout.connect(self.search_batch)
        self.thumbs_timer = QTimer(self, interval=25, singleShot=True)
        self.thumbs_timer.timeout.connect(self.render_thumbnails)
        self.resize_timer = QTimer(self, interval=90, singleShot=True)
        self.resize_timer.timeout.connect(self.fit_after_resize)
        self.update_state()
        QApplication.clipboard().dataChanged.connect(self.update_page_actions)
        self.updates = Updates(self, VERSION)

    def action(self, menu, key, title, callback, shortcut=None):
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        self.actions[key] = action

    def setup_actions(self):
        file = self.menuBar().addMenu("파일")
        edit = self.menuBar().addMenu("편집")
        markup = self.menuBar().addMenu("주석")
        pages = self.menuBar().addMenu("페이지")
        view = self.menuBar().addMenu("보기")
        self.action(file, "open", "PDF 열기…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.action(file, "from_images", "이미지로 PDF 만들기…", self.create_from_images)
        self.action(file, "save", "저장", self.save, QKeySequence.StandardKey.Save)
        self.action(file, "saveas", "다른 이름으로 저장…", self.save_as, QKeySequence.StandardKey.SaveAs)
        self.action(file, "close_tab", "현재 PDF 탭 닫기", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.action(file, "export", "페이지 내보내기…", self.export_pages)
        self.action(file, "print", "인쇄…", self.print_pdf, QKeySequence.StandardKey.Print)
        self.action(file, "security", "암호 보호…", self.security)
        self.action(file, "owner", "소유자 암호 입력…", self.unlock_owner)
        file.addSeparator()
        self.action(file, "default", "Windows 기본 PDF 앱 설정…", self.open_defaults)
        self.action(file, "quit", "종료", self.close, QKeySequence.StandardKey.Quit)
        self.action(edit, "undo", "실행 취소", lambda: self.history(False), QKeySequence.StandardKey.Undo)
        self.action(edit, "redo", "다시 실행", lambda: self.history(True), QKeySequence.StandardKey.Redo)
        edit.addSeparator()
        for mode, (title, _) in MODES.items():
            menu = markup if mode in GROUPS[1][1] else pages if mode == "crop" else edit
            self.action(menu, mode, title, lambda checked=False, target=mode: self.set_mode(target))
        edit.addSeparator()
        self.action(edit, "watermark", "워터마크 넣기…", lambda: self.mark_document("watermark"))
        self.action(edit, "numbers", "쪽 번호 넣기…", lambda: self.mark_document("number"))
        self.action(pages, "previous", "이전 페이지", lambda: self.go_page(self.page_index - 1), "PgUp")
        self.action(pages, "next", "다음 페이지", lambda: self.go_page(self.page_index + 1), "PgDown")
        pages.addSeparator()
        self.action(pages, "copy_pages", "페이지 복사", self.copy_selected_pages, QKeySequence.StandardKey.Copy)
        self.action(pages, "paste_pages", "현재 페이지 뒤에 붙여넣기", self.paste_pages, QKeySequence.StandardKey.Paste)
        pages.addSeparator()
        self.action(pages, "rotate", "오른쪽으로 90° 회전", self.turn_page)
        self.action(pages, "blank", "빈 페이지 추가", lambda: self.add_page(False))
        self.action(pages, "duplicate", "현재 페이지 복제", lambda: self.add_page(True))
        self.action(pages, "move_up", "페이지를 앞으로 이동", lambda: self.move_page(-1))
        self.action(pages, "move_down", "페이지를 뒤로 이동", lambda: self.move_page(1))
        self.action(pages, "delete", "현재 페이지 삭제…", self.delete_page)
        self.action(pages, "append", "다른 PDF 이어 붙이기…", self.append_pdf)
        self.action(view, "find", "텍스트 찾기", self.focus_search, QKeySequence.StandardKey.Find)
        self.action(view, "pagefit", "페이지 맞춤", lambda: self.set_zoom("page"), "Ctrl+0")
        self.action(view, "widthfit", "너비 맞춤", lambda: self.set_zoom("width"))
        self.action(view, "presentation", "전체 화면 발표", self.toggle_presentation, "F11")
        self.action(view, "next_tab", "다음 PDF 탭", lambda: self.step_tab(1), "Ctrl+Tab")
        self.action(view, "prev_tab", "이전 PDF 탭", lambda: self.step_tab(-1), "Ctrl+Shift+Tab")
        self.action(view, "updates", "업데이트 확인…", lambda: self.updates.check(manual=True))
        self.action(view, "about", "로컬 PDF 정보", self.about)

    def button(self, title, callback=None, action=None, name="", tooltip=""):
        button = QPushButton(title)
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if action:
            command = self.actions[action]
            button.clicked.connect(command.trigger)
            command.changed.connect(lambda: button.setEnabled(command.isEnabled()))
            button.setEnabled(command.isEnabled())
        else:
            button.clicked.connect(callback)
        if tooltip:
            button.setToolTip(tooltip)
        return button

    def setup_ui(self):
        host, root = panel("root", (0, 0, 0, 0), 0)
        self.setCentralWidget(host)
        masthead = QFrame(objectName="masthead")
        mast = QHBoxLayout(masthead)
        mast.setContentsMargins(17, 12, 17, 12)
        mast.setSpacing(11)
        brand_icon = QLabel()
        brand_icon.setPixmap(self.windowIcon().pixmap(QSize(32, 32)))
        mast.addWidget(brand_icon)
        mast.addWidget(label(APP, "brand"))
        mast.addWidget(label("│", "mastDivider"))
        self.file_label = label("열린 문서 없음", "filename")
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        mast.addWidget(self.file_label, 1)
        self.security_label = label("", "lockState")
        mast.addWidget(self.security_label)
        self.update_button = self.button("업데이트", lambda: self.updates.offer(), name="updateButton")
        self.update_button.hide()
        mast.addWidget(self.update_button)
        mast.addWidget(self.button("파일 열기", action="open", name="mastButton", tooltip="Ctrl+O"))
        mast.addWidget(self.button("저장", action="save", name="mastSave", tooltip="Ctrl+S"))
        root.addWidget(masthead)
        self.masthead = masthead

        self.tabs = QTabBar(objectName="documentTabs")
        self.tabs.setAccessibleName("열린 PDF 탭")
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.currentChanged.connect(self.activate_tab)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        root.addWidget(self.tabs)

        toolbar = QFrame(objectName="toolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(14, 9, 14, 9)
        tools.setSpacing(7)
        tools.addWidget(self.button("실행 취소", action="undo", tooltip="Ctrl+Z"))
        tools.addWidget(self.button("다시 실행", action="redo", tooltip="Ctrl+Y"))
        tools.addSpacing(14)
        tools.addWidget(self.button("‹", action="previous", name="arrow", tooltip="이전 페이지"))
        self.page_number = QSpinBox()
        self.page_number.setRange(0, 0)
        self.page_number.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_number.setKeyboardTracking(False)
        self.page_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_number.setFixedWidth(50)
        self.page_number.setAccessibleName("현재 페이지")
        self.page_number.valueChanged.connect(lambda value: self.go_page(value - 1))
        tools.addWidget(self.page_number)
        self.page_total = label("/ 0", "pageTotal", True)
        tools.addWidget(self.page_total)
        tools.addWidget(self.button("›", action="next", name="arrow", tooltip="다음 페이지"))
        tools.addSpacing(14)
        self.zoom_out = self.button("−", lambda: self.zoom_step(-1), name="arrow", tooltip="축소")
        self.zoom_in = self.button("+", lambda: self.zoom_step(1), name="arrow", tooltip="확대")
        tools.addWidget(self.zoom_out)
        self.zoom_box = QComboBox()
        self.zoom_box.setFixedWidth(115)
        self.zoom_box.setAccessibleName("확대 비율")
        for title, value in [("페이지 맞춤", "page"), ("너비 맞춤", "width"),
                             *[(f"{n}%", n / 100) for n in (25, 50, 75, 100, 125, 150, 200, 300, 400)]]:
            self.zoom_box.addItem(title, value)
        self.zoom_box.activated.connect(lambda index: self.set_zoom(self.zoom_box.itemData(index)))
        tools.addWidget(self.zoom_box)
        tools.addWidget(self.zoom_in)
        tools.addStretch(1)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("문서에서 텍스트 찾기")
        self.search_box.setAccessibleName("문서에서 텍스트 찾기")
        self.search_box.setFixedWidth(178)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textEdited.connect(self.reset_search)
        self.search_box.returnPressed.connect(lambda: self.find_next(1))
        tools.addWidget(self.search_box)
        self.search_count = label("", muted=True)
        tools.addWidget(self.search_count)
        self.find_prev = self.button("↑", lambda: self.find_next(-1), name="arrow", tooltip="이전 검색 결과")
        self.find_forward = self.button("↓", lambda: self.find_next(1), name="arrow", tooltip="다음 검색 결과")
        tools.addWidget(self.find_prev)
        tools.addWidget(self.find_forward)
        root.addWidget(toolbar)
        self.toolbar = toolbar

        work = QHBoxLayout()
        work.setSpacing(0)
        root.addLayout(work, 1)
        sidebar, left = panel("sidebar", (10, 13, 10, 9), 8)
        sidebar.setFixedWidth(163)
        self.sidebar = sidebar
        self.navigator = QComboBox()
        self.navigator.addItems(["페이지", "문서 목차"])
        left.addWidget(self.navigator)
        self.navigation = QStackedWidget()
        self.thumbs = QListWidget(objectName="thumbnails")
        self.thumbs.setViewMode(QListView.ViewMode.IconMode)
        self.thumbs.setFlow(QListView.Flow.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbs.setMovement(QListView.Movement.Static)
        self.thumbs.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.thumbs.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbs.setIconSize(QSize(94, 108))
        self.thumbs.setGridSize(QSize(128, 141))
        self.thumbs.currentRowChanged.connect(lambda row: self.go_page(row, sync_thumbnail=False))
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self.thumbnail_menu)
        self.thumbs.verticalScrollBar().valueChanged.connect(lambda: self.thumbs_timer.start())
        self.navigation.addWidget(self.thumbs)
        self.bookmarks = QTreeWidget(objectName="bookmarks")
        self.bookmarks.setHeaderHidden(True)
        self.bookmarks.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.bookmarks.itemActivated.connect(self.visit_bookmark)
        self.bookmarks.itemClicked.connect(self.visit_bookmark)
        self.navigation.addWidget(self.bookmarks)
        self.navigator.currentIndexChanged.connect(self.navigation.setCurrentIndex)
        left.addWidget(self.navigation, 1)
        work.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.page_view = PageView()
        self.page_view.selected.connect(self.on_selection)
        self.page_view.zoomed.connect(self.zoom_step)
        self.stack.addWidget(self.empty_view())
        self.stack.addWidget(self.page_view)
        work.addWidget(self.stack, 1)

        inspector, right = panel("inspector", (12, 13, 12, 12), 9)
        inspector.setFixedWidth(247)
        self.inspector = inspector
        route = QFrame(objectName="route")
        routes = QHBoxLayout(route)
        routes.setContentsMargins(3, 3, 3, 3)
        routes.setSpacing(1)
        right.addWidget(route)
        self.inspector_stack = QStackedWidget()
        right.addWidget(self.inspector_stack, 1)
        self.group_buttons = QButtonGroup(self)
        self.mode_buttons = {}
        self.mode_group = QButtonGroup(self)
        for index, (title, modes, actions) in enumerate(GROUPS):
            tab = self.button(title, lambda checked=False, tab_index=index: self.show_group(tab_index), name="routeTab")
            tab.setCheckable(True)
            self.group_buttons.addButton(tab, index)
            routes.addWidget(tab, 1)
            group, controls = panel("toolGroup", (0, 2, 0, 0), 5)
            for mode in modes:
                tool, description = MODES[mode]
                control = self.button(tool, action=mode, name="modeButton", tooltip=description)
                control.setIcon(tool_icon(mode))
                control.setIconSize(QSize(17, 17))
                control.setCheckable(True)
                self.mode_group.addButton(control)
                self.mode_buttons[mode] = control
                controls.addWidget(control)
            if modes and actions:
                controls.addSpacing(8)
            for key in actions:
                controls.addWidget(self.button(self.actions[key].text(), action=key, name="documentButton"))
            if index == 1:
                self.color_button = self.button("펜·밑줄 색상", self.choose_annotation_color, name="documentButton")
                controls.addSpacing(8)
                controls.addWidget(self.color_button)
                self.show_color()
            controls.addStretch(1)
            self.inspector_stack.addWidget(group)
        self.group_buttons.button(0).setChecked(True)
        work.addWidget(inspector)

        footer = QFrame(objectName="footer")
        status = QHBoxLayout(footer)
        status.setContentsMargins(13, 5, 13, 5)
        self.status = label("PDF를 열어 시작하세요.", "statusText", True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status.addWidget(self.status, 1)
        self.zoom_status = label("", "zoomStatus", True)
        status.addWidget(self.zoom_status)
        root.addWidget(footer)
        self.footer = footer
        self.mode_buttons["hand"].setChecked(True)

    def empty_view(self):
        screen, layout = panel("emptyView", (22, 22, 22, 22), 0)
        layout.addStretch(1)
        card, content = panel("emptyCard", (38, 36, 38, 35), 11)
        card.setFixedWidth(390)
        symbol = QLabel()
        symbol.setPixmap(self.windowIcon().pixmap(QSize(58, 58)))
        content.addWidget(symbol, alignment=Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(label("PDF 열기", "emptyTitle"), alignment=Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(label("문서를 이곳에 끌어 놓거나 파일을 선택하세요.", muted=True),
                          alignment=Qt.AlignmentFlag.AlignHCenter)
        content.addSpacing(6)
        content.addWidget(self.button("파일 선택", action="open", name="emptyOpen"),
                          alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return screen

    def update_state(self):
        active = self.doc is not None
        self.stack.setCurrentIndex(int(active))
        if active:
            doc = self.doc
            length = doc.pdf.page_count
            modified = "  *" if doc.dirty else ""
            self.setWindowTitle(f"{doc.name}{modified} | {APP}")
            self.file_label.setText(doc.name + modified)
            self.file_label.setToolTip(str(doc.path) if doc.path else "새 PDF")
            self.security_label.setText("암호 보호" if doc.protected else "")
            index = self.tabs.currentIndex()
            self.tabs.setTabText(index, doc.name.replace("&", "&&") + modified)
            self.tabs.setTabToolTip(index, self.file_label.toolTip())
        else:
            length = 0
            self.setWindowTitle(APP)
            self.file_label.setText("열린 문서 없음")
            self.file_label.setToolTip("")
            self.security_label.clear()
        self.tabs.setVisible(active and self.presentation_state is None)
        self.page_number.blockSignals(True)
        self.page_number.setRange(1 if active else 0, length)
        self.page_number.setValue(self.page_index + 1 if active else 0)
        self.page_number.blockSignals(False)
        self.page_total.setText(f"/ {length}")
        for widget in (self.page_number, self.zoom_box, self.zoom_in, self.zoom_out, self.search_box,
                       self.find_prev, self.find_forward):
            widget.setEnabled(active)
        for name in ("hand", "find", "pagefit", "widthfit", "presentation", "read_note"):
            self.actions[name].setEnabled(active)
        for name in ("edit", "insert", "redact", "image", "watermark", "numbers"):
            self.actions[name].setEnabled(active and doc.allowed(pdf.PDF_PERM_MODIFY))
        for name, permission in (("copy", pdf.PDF_PERM_COPY), ("export", pdf.PDF_PERM_COPY),
                                 ("print", pdf.PDF_PERM_PRINT), ("rotate", pdf.PDF_PERM_ASSEMBLE),
                                 ("append", pdf.PDF_PERM_ASSEMBLE), ("blank", pdf.PDF_PERM_ASSEMBLE),
                                 ("duplicate", pdf.PDF_PERM_ASSEMBLE), ("crop", pdf.PDF_PERM_ASSEMBLE)):
            self.actions[name].setEnabled(active and doc.allowed(permission))
        for name in GROUPS[1][1]:
            if name != "read_note":
                self.actions[name].setEnabled(active and doc.allowed(pdf.PDF_PERM_ANNOTATE))
        self.actions["previous"].setEnabled(active and self.page_index > 0)
        self.actions["next"].setEnabled(active and self.page_index < length - 1)
        self.actions["move_up"].setEnabled(self.actions["rotate"].isEnabled() and self.page_index > 0)
        self.actions["move_down"].setEnabled(self.actions["rotate"].isEnabled() and self.page_index < length - 1)
        self.actions["delete"].setEnabled(self.actions["rotate"].isEnabled() and length > 1)
        self.actions["security"].setEnabled(active and doc.can_change_security)
        self.actions["owner"].setEnabled(active and doc.protected and not doc.can_change_security)
        self.actions["save"].setEnabled(active and doc.dirty)
        self.actions["saveas"].setEnabled(active)
        self.actions["undo"].setEnabled(active and bool(doc.past))
        self.actions["redo"].setEnabled(active and bool(doc.future))
        self.actions["close_tab"].setEnabled(active and self.presentation_state is None)
        for name in ("next_tab", "prev_tab"):
            self.actions[name].setEnabled(self.tabs.count() > 1 and self.presentation_state is None)
        self.update_page_actions()

    def update_page_actions(self):
        doc = self.doc
        clipboard = QApplication.clipboard().mimeData()
        can_assemble = doc is not None and doc.allowed(pdf.PDF_PERM_ASSEMBLE)
        self.actions["copy_pages"].setEnabled(can_assemble and doc.allowed(pdf.PDF_PERM_COPY))
        self.actions["paste_pages"].setEnabled(can_assemble and clipboard is not None and clipboard.hasFormat(PAGE_CLIPBOARD))

    def error(self, title, error):
        QMessageBox.warning(self, title, str(error) or "이 작업을 완료할 수 없습니다.")

    def confirm_discard(self):
        if not self.doc or not self.doc.dirty:
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "변경 사항 저장", f"{self.doc.name}\n저장하지 않은 변경 사항이 있습니다.", parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        save = box.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("저장 안 함", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        return box.clickedButton() is skip or box.clickedButton() is save and self.save()

    def read_document(self, path):
        password, attempt = "", False
        while True:
            try:
                return Document(path, password)
            except PasswordRequired:
                prompt = "암호가 일치하지 않습니다. 다시 입력하세요." if attempt else f"{Path(path).name}\n열기 암호를 입력하세요."
                password, entered = QInputDialog.getText(self, "PDF 암호", prompt, QLineEdit.EchoMode.Password)
                if not entered:
                    return None
                attempt = True
            except Exception as error:
                self.error("PDF를 열 수 없습니다", error)
                return None

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF 열기", "", "PDF 문서 (*.pdf)")
        for path in paths:
            self.open_document(path)

    def open_document(self, path):
        resolved = Path(path).resolve()
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index).document.path == resolved:
                self.tabs.setCurrentIndex(index)
                return
        opened = self.read_document(path)
        if opened:
            self.load_document(opened)

    def load_document(self, opened):
        with QSignalBlocker(self.tabs):
            index = self.tabs.addTab(opened.name)
            self.tabs.setTabData(index, DocumentTab(opened))
            self.tabs.setCurrentIndex(index)
        self.activate_tab(index)

    def store_tab(self):
        tab = self.active_tab
        if tab is None:
            return
        tab.page = self.page_index
        tab.zoom = self.zoom
        tab.mode = self.page_view.mode
        tab.group = self.inspector_stack.currentIndex()
        tab.navigation = self.navigator.currentIndex()
        tab.query = self.search_box.text()
        tab.selected_pages = tuple(self.thumbs.row(item) for item in self.thumbs.selectedItems())
        center = self.page_view.viewport().rect().center()
        tab.scroll_position = self.page_view.mapToScene(center) / self.page_view.scale

    def activate_tab(self, index):
        tab = self.tabs.tabData(index) if index >= 0 else None
        if tab is not None and tab is self.active_tab:
            return
        self.store_tab()
        self.active_tab = tab
        self.doc = tab.document if tab else None
        self.page_index = tab.page if tab else 0
        self.zoom = tab.zoom if tab else "page"
        self.search_box.setText(tab.query if tab else "")
        self.reset_search()
        self.page_lines = None
        self.update_state()
        if tab is None:
            self.thumbs.clear()
            self.bookmarks.clear()
            self.zoom_status.clear()
            self.status.setText("PDF를 열어 시작하세요.")
            return
        self.set_mode(tab.mode if self.actions[tab.mode].isEnabled() else "hand", reveal=False)
        self.group_buttons.button(tab.group).setChecked(True)
        self.inspector_stack.setCurrentIndex(tab.group)
        self.navigator.setCurrentIndex(tab.navigation)
        self.refresh_thumbnails()
        if tab.selected_pages:
            with QSignalBlocker(self.thumbs):
                self.thumbs.clearSelection()
                for page in tab.selected_pages:
                    if item := self.thumbs.item(page):
                        item.setSelected(True)
        self.update_zoom_box()
        self.render_page()
        if tab.scroll_position is not None:
            self.page_view.centerOn(tab.scroll_position * self.page_view.scale)
        self.page_view.setFocus()

    def step_tab(self, step):
        if self.tabs.count() > 1 and self.presentation_state is None:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def close_tab(self, index):
        if not 0 <= index < self.tabs.count():
            return
        self.tabs.setCurrentIndex(index)
        if not self.confirm_discard():
            return
        self.doc.pdf.close()
        self.active_tab = None
        self.doc = None
        with QSignalBlocker(self.tabs):
            self.tabs.removeTab(index)
        self.activate_tab(self.tabs.currentIndex())

    def confirm_close_documents(self):
        original = self.tabs.currentIndex()
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index).document.dirty:
                self.tabs.setCurrentIndex(index)
                if not self.confirm_discard():
                    return False
        self.tabs.setCurrentIndex(original)
        return True

    def choose_path(self, suffix="_편집", extension="pdf"):
        folder = self.doc.path.parent if self.doc.path else Path(QDir.homePath())
        default = str(folder / (Path(self.doc.name).stem + suffix + "." + extension))
        file_type = f"{extension.upper()} (*.{extension})"
        picker = QFileDialog(self, "파일 저장", default, file_type)
        picker.setFileMode(QFileDialog.FileMode.AnyFile)
        picker.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        picker.setDefaultSuffix(extension)
        return picker.selectedFiles()[0] if picker.exec() and picker.selectedFiles() else ""

    def save_as(self):
        path = self.choose_path()
        return bool(path) and self.write_document(path)

    def save(self):
        if not self.doc or not self.doc.dirty:
            return True
        return self.write_document(self.doc.path) if self.doc.path else self.save_as()

    def write_document(self, path, password=None):
        target = Path(path).resolve()
        for index in range(self.tabs.count()):
            other = self.tabs.tabData(index).document
            if other is not self.doc and other.path == target:
                self.error("PDF 저장", "다른 탭에서 열려 있는 파일입니다. 다른 이름으로 저장하세요.")
                return False
        signature_flags = self.doc.pdf.get_sigflags()
        if signature_flags > 0 and signature_flags & 2:
            answer = QMessageBox.question(self, "디지털 서명", "이 PDF의 기존 디지털 서명이 저장 후 무효화될 수 있습니다. 계속 저장할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            self.doc.save(path, security=password)
        except Exception as error:
            self.error("PDF 저장 실패", error)
            return False
        self.update_state()
        self.status.setText(f"저장 완료 · {self.doc.path.name}")
        return True

    def security(self):
        dialog = PasswordDialog(self, self.doc.protected, self.doc.pdf.permissions)
        if dialog.exec():
            protected = bool(dialog.protection.user or dialog.protection.owner)
            path = self.choose_path("_암호" if protected else "_암호해제")
            if path:
                self.write_document(path, dialog.protection)

    def create_from_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF에 담을 이미지 선택", "", IMAGE_FILTER)
        if not paths:
            return
        try:
            doc = document_from_images(image_bytes(path) for path in paths)
        except Exception as error:
            self.error("이미지로 PDF 만들기", error)
            return
        self.load_document(doc)
        self.status.setText(f"이미지 {len(paths)}개로 PDF를 만들었습니다. Ctrl+S로 저장하세요.")

    def export_pages(self):
        dialog = PagesDialog(self, self.doc.pdf.page_count, self.page_index + 1, "export")
        if not dialog.exec():
            return
        kind, indices = dialog.kind.currentData(), dialog.indices
        if kind in {"pdf", "txt"} or len(indices) == 1:
            path = self.choose_path("_내보내기", kind)
            if not path:
                return
            targets = [Path(path)]
        else:
            folder = QFileDialog.getExistingDirectory(self, "페이지 이미지를 저장할 폴더",
                                                       str(self.doc.path.parent) if self.doc.path else QDir.homePath())
            if not folder:
                return
            stem = Path(self.doc.name).stem
            targets = [Path(folder) / f"{stem}_{index + 1:03}.{kind}" for index in indices]
            conflicts = sum(path.exists() for path in targets)
            if conflicts and QMessageBox.question(self, "이미지 파일 저장", f"기존 이미지 {conflicts}개를 덮어쓸까요?") != QMessageBox.StandardButton.Yes:
                return
        if self.doc.path and any(path.resolve() == self.doc.path for path in targets):
            self.error("페이지 내보내기", "원본 PDF와 다른 이름으로 저장하세요.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if kind == "pdf":
                self.doc.extract(indices, targets[0])
            elif kind == "txt":
                contents = "\f\n".join(self.doc.pdf[index].get_text(sort=True) for index in indices)
                if not contents.replace("\f", "").strip():
                    raise ValueError("선택한 페이지에서 텍스트를 찾지 못했습니다. 이미지 형식으로 내보낼 수 있습니다.")
                atomic_write(targets[0], contents.encode("utf-8-sig"))
            else:
                for index, path in zip(indices, targets):
                    page = self.doc.pdf[index]
                    dpi = min(dialog.dpi.value(), max(1, int(6000 * 72 / max(page.rect.width, page.rect.height))))
                    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                    atomic_write(path, pixmap.tobytes("jpeg" if kind == "jpg" else "png"))
            self.status.setText(f"{len(indices)}페이지를 {kind.upper()} 형식으로 내보냈습니다.")
        except Exception as error:
            QApplication.restoreOverrideCursor()
            self.error("페이지 내보내기", error)
            return
        QApplication.restoreOverrideCursor()

    def mark_document(self, operation):
        dialog = PagesDialog(self, self.doc.pdf.page_count, self.page_index + 1, operation)
        if not dialog.exec():
            return
        numbering = operation == "number"
        text = "0123456789" if numbering else dialog.text.text().strip()
        size = 11 if numbering else dialog.size.value()
        opacity = .9 if numbering else dialog.opacity.value() / 100

        def apply(doc):
            font = embedding_font(DEFAULT_FACE, text)
            for offset, index in enumerate(dialog.indices):
                mark = str(dialog.first.value() + offset) if numbering else text
                mark_page(doc[index], mark, DEFAULT_FACE, size, opacity, at_bottom=numbering, font=font)

        self.mutate("쪽 번호 넣기" if numbering else "워터마크 넣기", pdf.PDF_PERM_MODIFY, apply, structure=True)

    def unlock_owner(self):
        password, accepted = QInputDialog.getText(self, "PDF 소유자 권한", "소유자 암호를 입력하세요.",
                                                  QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            if not self.doc.authorize_owner(password):
                raise ValueError("소유자 암호가 일치하지 않습니다.")
        except Exception as error:
            self.error("소유자 권한", error)
            return
        self.update_state()
        self.status.setText("소유자 권한으로 편집할 수 있습니다.")

    def open_defaults(self):
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications") as key:
                winreg.QueryValueEx(key, APP)
            target = "ms-settings:defaultapps?registeredAppUser=" + quote(APP)
        except OSError:
            target = "ms-settings:defaultapps"
        try:
            os.startfile(target)
        except OSError:
            os.startfile("ms-settings:defaultapps")

    def about(self):
        QMessageBox.about(self, APP, f"<b>{APP} {VERSION}</b><p>Windows용 PDF 뷰어 및 편집기</p>"
                          "<p>PDF 처리는 이 PC에서 이루어집니다.</p><p>PyMuPDF · Qt for Python</p>")

    def show_group(self, index):
        if self.page_view.mode not in GROUPS[index][1]:
            self.set_mode("hand", reveal=False)
        self.inspector_stack.setCurrentIndex(index)

    def set_mode(self, mode, reveal=True):
        if not self.doc or not self.actions[mode].isEnabled():
            return
        self.mode_buttons[mode].setChecked(True)
        self.page_view.set_mode(mode)
        if reveal:
            for index, (_, modes, _) in enumerate(GROUPS):
                if mode in modes:
                    self.group_buttons.button(index).setChecked(True)
                    self.inspector_stack.setCurrentIndex(index)
                    break
        self.status.setText(MODES[mode][1])
        if mode == "edit":
            try:
                if self.page_lines is None:
                    self.page_lines = list(text_lines(self.doc.pdf[self.page_index]))
                self.page_view.lines = self.page_lines
            except Exception as error:
                self.error("텍스트를 읽을 수 없습니다", error)

    def go_page(self, index, sync_thumbnail=True):
        if not self.doc or index == self.page_index or not 0 <= index < self.doc.pdf.page_count:
            return
        self.page_index = index
        self.page_lines = None
        if sync_thumbnail:
            self.select_thumbnail()
        self.update_state()
        self.render_page()

    def actual_zoom(self):
        if isinstance(self.zoom, float):
            return self.zoom
        page = self.doc.pdf[self.page_index].rect
        viewport = self.page_view.viewport().size()
        margin = self.page_view.margin * 2 + 12
        width = (viewport.width() - margin) / page.width
        height = (viewport.height() - margin) / page.height
        return max(.05, min(4, width, height) if self.zoom == "page" else min(4, width))

    def set_zoom(self, value):
        if not self.doc:
            return
        self.zoom = value
        self.update_zoom_box()
        self.render_page(keep_position=isinstance(value, float))

    def update_zoom_box(self):
        index = self.zoom_box.findData(self.zoom)
        if index < 0:
            if self.zoom_box.count() > 11:
                self.zoom_box.removeItem(11)
            self.zoom_box.addItem(f"{self.zoom:.0%}", self.zoom)
            index = self.zoom_box.count() - 1
        self.zoom_box.setCurrentIndex(index)

    def zoom_step(self, step):
        if self.doc:
            scale = self.page_view.scale * (1.22 if step > 0 else 1 / 1.22)
            self.set_zoom(round(max(.1, min(4, scale)), 2))

    def render_page(self, keep_position=False):
        if not self.doc:
            return
        try:
            scale = self.actual_zoom()
            self.page_view.show_page(self.doc.pdf[self.page_index], scale, keep_position)
            self.zoom_status.setText(f"{scale:.0%}")
            if self.page_view.mode == "edit":
                if self.page_lines is None:
                    self.page_lines = list(text_lines(self.doc.pdf[self.page_index]))
                self.page_view.lines = self.page_lines
            self.show_search_marks()
        except Exception as error:
            self.error("페이지 표시 실패", error)

    def fit_after_resize(self):
        if self.doc and isinstance(self.zoom, str):
            self.render_page(keep_position=self.zoom == "width")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "resize_timer") and self.doc:
            self.resize_timer.start()
            self.thumbs_timer.start()

    def select_thumbnail(self):
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(self.page_index)
        item = self.thumbs.currentItem()
        if item and not self.thumbs.viewport().rect().contains(self.thumbs.visualItemRect(item)):
            self.thumbs.scrollToItem(item)
        self.thumbs.blockSignals(False)
        self.thumbs_timer.start()

    def thumbnail_menu(self, position):
        if not self.doc:
            return
        menu = QMenu(self)
        menu.addAction(self.actions["copy_pages"])
        menu.addAction(self.actions["paste_pages"])
        menu.exec(self.thumbs.viewport().mapToGlobal(position))

    def copy_selected_pages(self):
        indices = sorted(self.thumbs.row(item) for item in self.thumbs.selectedItems()) or [self.page_index]
        try:
            fragment = self.doc.copy_pages(indices)
        except Exception as error:
            self.error("페이지 복사", error)
            return
        mime = QMimeData()
        mime.setData(PAGE_CLIPBOARD, fragment)
        QApplication.clipboard().setMimeData(mime)
        self.status.setText(f"{len(indices)}페이지를 복사했습니다. 삽입할 위치에서 Ctrl+V를 누르세요.")

    def paste_pages(self):
        clipboard = QApplication.clipboard().mimeData()
        if clipboard is None or not clipboard.hasFormat(PAGE_CLIPBOARD):
            return
        try:
            with pdf.open(stream=bytes(clipboard.data(PAGE_CLIPBOARD)), filetype="pdf") as copied:
                if not copied.is_pdf or copied.is_encrypted or not copied.page_count:
                    raise ValueError("클립보드에서 붙여넣을 PDF 페이지를 찾지 못했습니다.")
                first = self.page_index + 1
                start = first if first < self.doc.pdf.page_count else -1
                self.mutate(f"{copied.page_count}페이지 붙여넣기", pdf.PDF_PERM_ASSEMBLE,
                            lambda target: target.insert_pdf(copied, start_at=start), first, structure=True)
        except Exception as error:
            self.error("페이지 붙여넣기", error)

    def refresh_thumbnails(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        placeholder = QPixmap(94, 108)
        placeholder.fill(QColor("#edf1f3"))
        icon = QIcon(placeholder)
        for index in range(self.doc.pdf.page_count):
            item = QListWidgetItem(icon, str(index + 1))
            item.setSizeHint(QSize(130, 138))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbs.addItem(item)
        self.thumbs.blockSignals(False)
        self.select_thumbnail()
        self.refresh_bookmarks()

    def refresh_bookmarks(self):
        self.bookmarks.clear()
        parents = []
        for level, title, index in self.doc.pdf.get_toc():
            level = max(1, level)
            parents = parents[:level - 1]
            row = QTreeWidgetItem(parents[-1] if parents else self.bookmarks, [title])
            row.setData(0, Qt.ItemDataRole.UserRole, index - 1)
            row.setToolTip(0, title)
            parents.append(row)
        outline = bool(self.bookmarks.topLevelItemCount())
        if not outline:
            QTreeWidgetItem(self.bookmarks, ["목차 없음"])
        else:
            self.bookmarks.expandToDepth(0)

    def visit_bookmark(self, item, _):
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and index >= 0:
            self.go_page(index)

    def choose_annotation_color(self):
        color = QColorDialog.getColor(self.annotation_color, self, "펜·밑줄 색상")
        if color.isValid():
            self.annotation_color = color
            self.page_view.ink_color = color
            self.show_color()

    def show_color(self):
        swatch = QPixmap(14, 14)
        swatch.fill(self.annotation_color)
        self.color_button.setIcon(QIcon(swatch))

    def render_thumbnails(self):
        if not self.doc:
            return
        viewport = self.thumbs.viewport().rect()
        for index in range(self.thumbs.count()):
            item = self.thumbs.item(index)
            if item.data(Qt.ItemDataRole.UserRole) or not viewport.intersects(self.thumbs.visualItemRect(item)):
                continue
            try:
                page = self.doc.pdf[index]
                scale = min(91 / page.rect.width, 106 / page.rect.height)
                pixmap = QPixmap.fromImage(page_image(page, scale))
                icon = QIcon(pixmap)
                icon.addPixmap(pixmap, QIcon.Mode.Selected)
                item.setIcon(icon)
            except Exception:
                item.setToolTip("미리보기를 표시할 수 없습니다.")
            item.setData(Qt.ItemDataRole.UserRole, True)

    def mutate(self, title, permission, callback, next_page=None, structure=False):
        try:
            self.doc.change(self.page_index, permission, callback)
        except Exception as error:
            self.error(title, error)
            return False
        self.refresh_edit(next_page, structure)
        self.status.setText(f"{title} 완료 · Ctrl+Z로 실행 취소")
        return True

    def refresh_edit(self, next_page=None, structure=False):
        self.page_index = min(self.doc.pdf.page_count - 1, self.page_index if next_page is None else next_page)
        self.page_lines = None
        self.reset_search()
        self.update_state()
        if structure:
            self.refresh_thumbnails()
        else:
            self.thumbs.item(self.page_index).setData(Qt.ItemDataRole.UserRole, False)
            self.thumbs_timer.start()
        self.render_page(keep_position=not structure)

    def on_selection(self, mode, value):
        if not self.doc:
            return
        index = self.page_index
        if mode == "edit" and value is None:
            self.status.setText("편집할 텍스트를 찾지 못했습니다. 스캔 이미지 위에는 새 텍스트를 삽입할 수 있습니다.")
        elif mode in {"edit", "insert"}:
            line = value if mode == "edit" else None
            dialog = TextDialog(self, line, self.last_text_settings)
            while dialog.exec():
                text, face, size, color = dialog.result_values
                color_tuple = color.redF(), color.greenF(), color.blueF()
                if self.mutate(MODES[mode][0], pdf.PDF_PERM_MODIFY,
                               lambda doc: write_text(doc[index], None if line else value, text, face, size, color_tuple, line)):
                    self.last_text_settings = face, size, color
                    break
        elif mode == "redact":
            box = QMessageBox(QMessageBox.Icon.Warning, "영역 삭제",
                              "선택 영역의 텍스트와 이미지 내용을 제거합니다. 영역에 걸친 선이나 도형은 전체가 삭제될 수 있습니다.",
                              parent=self)
            white = box.addButton("흰색으로 삭제", QMessageBox.ButtonRole.AcceptRole)
            black = box.addButton("검은색으로 삭제", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() in (white, black):
                self.mutate("영역 삭제", pdf.PDF_PERM_MODIFY,
                            lambda doc: redact_area(doc[index], value, black=box.clickedButton() is black))
        elif mode in {"highlight", "underline", "strike", "rectangle", "ink"}:
            self.annotate(mode, value)
        elif mode in {"memo", "read_note", "erase_note"}:
            self.note_at(mode, value)
        elif mode == "image":
            path, _ = QFileDialog.getOpenFileName(self, "삽입할 이미지·도장 선택", "", IMAGE_FILTER)
            if path:
                def place(doc):
                    page = doc[index]
                    page.insert_image(value, stream=image_bytes(path), rotate=page.rotation, keep_proportion=True)
                self.mutate("이미지·도장 삽입", pdf.PDF_PERM_MODIFY, place)
        elif mode == "crop":
            if value.width < 12 or value.height < 12:
                self.status.setText("자를 영역을 더 크게 지정하세요.")
                return
            if QMessageBox.question(self, "페이지 자르기", "선택한 영역만 페이지에 보이게 할까요? 내용 자체를 제거하려면 영역 삭제를 사용하세요.") == QMessageBox.StandardButton.Yes:
                def crop(doc):
                    page = doc[index]
                    visible = value & (page.rect * page.derotation_matrix)
                    x, y = page.cropbox_position
                    page.set_cropbox(visible + (x, y, x, y))
                self.mutate("페이지 자르기", pdf.PDF_PERM_ASSEMBLE, crop)
        elif mode == "copy":
            text = self.doc.pdf[index].get_textbox(value)
            if text.strip():
                QApplication.clipboard().setText(text)
            self.status.setText("텍스트를 복사했습니다." if text.strip() else "선택 영역에서 텍스트를 찾지 못했습니다.")

    def annotate(self, mode, value):
        index = self.page_index
        color = (self.annotation_color.redF(), self.annotation_color.greenF(), self.annotation_color.blueF())

        def apply(doc):
            page = doc[index]
            if mode in {"highlight", "underline", "strike"}:
                add_markup(page, mode, value, (1, .84, .20) if mode == "highlight" else color)
                return
            annot = page.add_ink_annot([[tuple(point) for point in value]]) if mode == "ink" else page.add_rect_annot(value)
            annot.set_colors(stroke=color)
            annot.set_border(width=2)
            annot.update()

        self.mutate(MODES[mode][0], pdf.PDF_PERM_ANNOTATE, apply)

    def note_at(self, mode, point):
        index = self.page_index
        page = self.doc.pdf[index]
        if mode == "memo":
            text, accepted = QInputDialog.getMultiLineText(self, "메모 추가", "메모 내용")
            if accepted and text.strip():
                self.mutate("메모 추가", pdf.PDF_PERM_ANNOTATE,
                            lambda doc: doc[index].add_text_annot(point, text.strip()))
            return
        notes = list(page.annots(types=[pdf.PDF_ANNOT_TEXT]) if mode == "read_note" else page.annots())
        targets = [annot for annot in notes if (annot.rect + (-2, -2, 2, 2)).contains(point)]
        if not targets:
            self.status.setText("이 위치에서 주석을 찾지 못했습니다.")
            return
        target = min(targets, key=lambda annot: annot.rect.get_area())
        xref = target.xref
        if mode == "erase_note":
            if QMessageBox.question(self, "주석 지우기", "선택한 주석을 지울까요?") == QMessageBox.StandardButton.Yes:
                def remove(doc):
                    loaded = doc[index]
                    loaded.delete_annot(loaded.load_annot(xref))
                self.mutate("주석 지우기", pdf.PDF_PERM_ANNOTATE, remove)
            return
        content = target.info.get("content", "")
        if not self.doc.allowed(pdf.PDF_PERM_ANNOTATE):
            box = QMessageBox(QMessageBox.Icon.Information, "PDF 메모", content, parent=self)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.exec()
            return
        text, accepted = QInputDialog.getMultiLineText(self, "메모 열기·수정", "메모 내용", content)
        if accepted and text.strip() and text.strip() != content:
            def replace(doc):
                loaded = doc[index]
                annot = loaded.load_annot(xref)
                annot.set_info(content=text.strip())
                annot.update()
            self.mutate("메모 수정", pdf.PDF_PERM_ANNOTATE, replace)

    def turn_page(self):
        index = self.page_index

        def rotate(doc):
            page = doc[index]
            page.set_rotation(page.rotation + 90)

        self.mutate("페이지 회전", pdf.PDF_PERM_ASSEMBLE, rotate)

    def add_page(self, duplicate):
        index = self.page_index

        def add(doc):
            if duplicate:
                doc.fullcopy_page(index, to=-1 if index + 1 == doc.page_count else index + 1)
            else:
                bounds = doc[index].rect
                doc.new_page(pno=index + 1, width=bounds.width, height=bounds.height)

        self.mutate("페이지 복제" if duplicate else "빈 페이지 추가", pdf.PDF_PERM_ASSEMBLE, add,
                    index + 1, structure=True)

    def move_page(self, direction):
        index = self.page_index
        before = index - 1 if direction < 0 else index + 2
        if before == self.doc.pdf.page_count:
            before = -1
        self.mutate("페이지 이동", pdf.PDF_PERM_ASSEMBLE, lambda doc: doc.move_page(index, before),
                    index + direction, structure=True)

    def delete_page(self):
        index = self.page_index
        if QMessageBox.question(self, "페이지 삭제", f"{index + 1}페이지를 삭제할까요?") == QMessageBox.StandardButton.Yes:
            self.mutate("페이지 삭제", pdf.PDF_PERM_ASSEMBLE, lambda doc: doc.delete_page(index), structure=True)

    def append_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "이어 붙일 PDF 선택", "", "PDF 문서 (*.pdf)")
        if not paths:
            return
        files = []
        try:
            for path in paths:
                other = self.read_document(path)
                if not other:
                    return
                files.append(other)
                if not other.allowed(pdf.PDF_PERM_COPY):
                    self.error("PDF 이어 붙이기", f"{other.name}에 복사 권한이 없습니다.")
                    return
            first = self.doc.pdf.page_count
            def append(doc):
                for other in files:
                    doc.insert_pdf(other.pdf)
            self.mutate("PDF 이어 붙이기", pdf.PDF_PERM_ASSEMBLE, append, first, structure=True)
        finally:
            for other in files:
                other.pdf.close()

    def toggle_presentation(self):
        if self.presentation_state:
            mode, zoom, previous = self.presentation_state
            self.presentation_state = None
            self.setWindowState(previous)
            for widget in self.chrome():
                widget.show()
            self.set_mode(mode)
            self.set_zoom(zoom)
        else:
            self.presentation_state = self.page_view.mode, self.zoom, self.windowState()
            self.set_mode("hand")
            for widget in self.chrome():
                widget.hide()
            self.showFullScreen()
            self.set_zoom("page")
            self.page_view.setFocus()
        self.update_state()

    def chrome(self):
        return self.menuBar(), self.masthead, self.tabs, self.toolbar, self.sidebar, self.inspector, self.footer

    def keyPressEvent(self, event):
        if self.presentation_state:
            if event.key() == Qt.Key.Key_Escape:
                self.toggle_presentation()
                return
            if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Space}:
                self.go_page(self.page_index + (-1 if event.key() == Qt.Key.Key_Left else 1))
                return
        super().keyPressEvent(event)

    def history(self, redo):
        try:
            page = self.doc.step(self.page_index, redo=redo)
            self.refresh_edit(page, structure=True)
            self.status.setText("다시 실행했습니다." if redo else "실행 취소했습니다.")
        except Exception as error:
            self.error("편집 기록", error)

    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def reset_search(self, *_):
        self.search_timer.stop()
        self.search_hits.clear()
        self.search_term = ""
        self.search_index = 0
        self.search_count.clear()
        self.page_view.search_marks([])

    def find_next(self, direction):
        term = self.search_box.text().strip()
        if not term:
            return
        if term != self.search_term:
            self.reset_search()
            self.search_term, self.search_page, self.search_direction = term, 0, direction
            self.search_count.setText("검색 중…")
            self.search_timer.start()
        elif self.search_hits and not self.search_timer.isActive():
            self.show_hit((self.search_index + direction) % len(self.search_hits))

    def search_batch(self):
        try:
            stop = min(self.doc.pdf.page_count, self.search_page + 6)
            for index in range(self.search_page, stop):
                self.search_hits.extend((index, rect) for rect in self.doc.pdf[index].search_for(self.search_term))
            self.search_page = stop
            if stop == self.doc.pdf.page_count:
                self.search_timer.stop()
                if self.search_hits:
                    start = next((i for i, (page, _) in enumerate(self.search_hits) if page >= self.page_index), 0)
                    self.show_hit(start if self.search_direction > 0 else (start - 1) % len(self.search_hits))
                else:
                    self.search_count.setText("결과 없음")
        except Exception as error:
            self.reset_search()
            self.error("텍스트 찾기", error)

    def show_hit(self, index):
        self.search_index = index
        self.go_page(self.search_hits[index][0])
        self.search_count.setText(f"{index + 1} / {len(self.search_hits)}")
        self.show_search_marks()

    def show_search_marks(self):
        hits = []
        active = None
        for index, (page, rect) in enumerate(self.search_hits):
            if page == self.page_index:
                if index == self.search_index:
                    active = len(hits)
                hits.append(rect)
        self.page_view.search_marks(hits, active)

    def print_pdf(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        resolution = 240 if self.doc.allowed(pdf.PDF_PERM_PRINT_HQ) else 120
        printer.setResolution(resolution)
        printer.setDocName(self.doc.name)
        dialog = QPrintDialog(printer, self)
        dialog.setMinMax(1, self.doc.pdf.page_count)
        dialog.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage)
        if not dialog.exec():
            return
        first, last = 0, self.doc.pdf.page_count - 1
        if printer.printRange() == QPrinter.PrintRange.CurrentPage:
            first = last = self.page_index
        elif printer.printRange() == QPrinter.PrintRange.PageRange:
            first, last = max(0, printer.fromPage() - 1), min(last, printer.toPage() - 1)
        painter = QPainter()
        try:
            if not painter.begin(printer):
                raise ValueError("프린터를 시작할 수 없습니다.")
            indices = range(first, last + 1)
            if printer.pageOrder() == QPrinter.PageOrder.LastPageFirst:
                indices = reversed(indices)
            for iteration, index in enumerate(indices):
                if iteration and not printer.newPage():
                    raise ValueError("프린터에 다음 페이지를 보낼 수 없습니다.")
                page = self.doc.pdf[index]
                area = printer.pageRect(QPrinter.Unit.DevicePixel)
                scale = min(area.width() / page.rect.width, area.height() / page.rect.height)
                image = page_image(page, min(scale, resolution / 72, 4500 / max(page.rect.width, page.rect.height)))
                area.setX(0)
                area.setY(0)
                area.setWidth(page.rect.width * scale)
                area.setHeight(page.rect.height * scale)
                area.moveCenter(printer.pageRect(QPrinter.Unit.DevicePixel).center() - printer.pageRect(QPrinter.Unit.DevicePixel).topLeft())
                painter.drawImage(area, image)
        except Exception as error:
            self.error("인쇄 실패", error)
        finally:
            if painter.isActive():
                painter.end()

    def dragEnterEvent(self, event):
        if self.dropped_paths(event):
            event.acceptProposedAction()

    @staticmethod
    def dropped_paths(event):
        return [url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")]

    def dropEvent(self, event):
        paths = self.dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            for path in paths:
                self.open_document(path)

    def closeEvent(self, event):
        if self.closing_for_update or self.confirm_close_documents():
            self.search_timer.stop()
            self.thumbs_timer.stop()
            self.resize_timer.stop()
            for index in range(self.tabs.count()):
                self.tabs.tabData(index).document.pdf.close()
            self.doc = None
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet((ROOT / "assets/style.qss").read_text(encoding="utf-8"))
    window = MainWindow()
    window.show()
    paths = [path for path in sys.argv[1:] if Path(path).is_file()]
    if paths:
        def open_files():
            for path in paths:
                window.open_document(path)
        QTimer.singleShot(0, open_files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

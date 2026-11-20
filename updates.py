import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox


REPOSITORY = "kijung4290/local-pdf"
API = f"https://api.github.com/repos/{REPOSITORY}"
SITE = f"https://github.com/{REPOSITORY}"
MAX_INSTALLER = 250 * 1024 * 1024
RELEASE_HOSTS = {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in RELEASE_HOSTS or url.username or url.password:
            raise ValueError("GitHub 외부 주소로 이동한 다운로드를 중단했습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(GitHubRedirects())


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str


def version_tuple(tag):
    match = re.fullmatch(r"v?(\d{1,5})\.(\d{1,5})\.(\d{1,5})", tag)
    if match is None:
        raise ValueError("지원하지 않는 GitHub 버전 형식입니다.")
    return tuple(map(int, match.groups()))


def read_release(payload, current):
    tag = payload.get("tag_name", "")
    if payload.get("draft") or payload.get("prerelease") or version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix("v")
    name = f"LocalPDF-Setup-{version}-x64.exe"
    url = f"{SITE}/releases/download/{tag}/{name}"
    for asset in payload.get("assets", []):
        digest = asset.get("digest") or ""
        size = asset.get("size")
        if (asset.get("name") == name and asset.get("browser_download_url") == url
                and re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
                and type(size) is int and 0 < size <= MAX_INSTALLER):
            return Release(version, url, size, digest[7:])
    raise ValueError("릴리스에서 검증 가능한 Windows 설치 파일을 찾지 못했습니다.")


def request(url, accept):
    return Request(url, headers={"User-Agent": "LocalPDF-Updater", "Accept": accept,
                                "X-GitHub-Api-Version": "2022-11-28"})


def fetch_release(current):
    try:
        with OPENER.open(request(API + "/releases/latest", "application/vnd.github+json"), timeout=12) as response:
            data = response.read(1024 * 1024)
        return read_release(json.loads(data), current)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("GitHub에서 공개 릴리스를 찾지 못했습니다.") from error
        raise


def download(release, progress):
    fd, name = tempfile.mkstemp(prefix=f"LocalPDF-{release.version}-", suffix=".exe")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, OPENER.open(request(release.url, "application/octet-stream"), timeout=30) as source:
            count = 0
            last = -1
            while chunk := source.read(256 * 1024):
                count += len(chunk)
                if count > release.size:
                    raise ValueError("다운로드한 설치 파일의 크기가 일치하지 않습니다.")
                target.write(chunk)
                percent = int(count * 100 / release.size)
                if percent != last:
                    progress(percent)
                    last = percent
        with path.open("rb") as saved:
            if path.stat().st_size != release.size or hashlib.file_digest(saved, "sha256").hexdigest() != release.digest:
                raise ValueError("설치 파일의 SHA-256 검증에 실패했습니다.")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def launch_setup(installer):
    arguments = [str(installer), "/SILENT", "/NORESTART", "/LOCALPDFUPDATE=1"]
    bundle = getattr(sys, "_MEIPASS", None)
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    if bundle:
        folder = Path(sys.executable).resolve().parent
        if (folder / "unins000.exe").exists():
            arguments.append(f"/DIR={folder}")
        locations = environment.get("PATH", "").split(os.pathsep)
        environment["PATH"] = os.pathsep.join(location for location in locations
                                              if location and not Path(location).is_relative_to(bundle))
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        subprocess.Popen(arguments, env=environment, close_fds=True)
    finally:
        if bundle:
            ctypes.windll.kernel32.SetDllDirectoryW(ctypes.c_wchar_p(bundle))


class Updates(QObject):
    checked = Signal(object, object, bool)
    downloaded = Signal(object, object)
    progress = Signal(int)

    def __init__(self, window, version):
        super().__init__(window)
        self.window = window
        self.version = version
        self.release = None
        self.busy = False
        self.checked.connect(self.on_checked)
        self.downloaded.connect(self.on_downloaded)
        self.progress.connect(self.on_progress)
        self.timer = QTimer(self, interval=10 * 60 * 1000)
        self.timer.timeout.connect(self.check)
        if getattr(sys, "frozen", False):
            QTimer.singleShot(4500, self.check)
            self.timer.start()

    def check(self, manual=False):
        if self.busy:
            if manual:
                self.window.status.setText("업데이트 작업을 진행하고 있습니다.")
            return
        self.busy = True

        def work():
            try:
                release = fetch_release(self.version)
            except Exception as error:
                self.checked.emit(None, error, manual)
            else:
                self.checked.emit(release, None, manual)

        Thread(target=work, daemon=True).start()

    def on_checked(self, release, error, manual):
        self.busy = False
        if error:
            if manual:
                self.window.error("업데이트 확인", error)
            return
        self.release = release
        button = self.window.update_button
        button.setVisible(self.release is not None)
        if self.release:
            button.setText(f"{release.version} 업데이트")
            if manual:
                self.offer()
        elif manual:
            QMessageBox.information(self.window, "업데이트 확인", f"최신 버전 {self.version}을 사용하고 있습니다.")

    def offer(self):
        if not self.release or self.busy:
            return
        release = self.release
        box = QMessageBox(QMessageBox.Icon.Information, "로컬 PDF 업데이트",
                          f"새 버전 {release.version}을 설치할까요? 설치가 끝나면 로컬 PDF를 다시 엽니다.",
                          parent=self.window)
        install = box.addButton("다운로드하고 설치", QMessageBox.ButtonRole.AcceptRole)
        notes = box.addButton("릴리스 보기", QMessageBox.ButtonRole.ActionRole)
        box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is notes:
            os.startfile(SITE + "/releases/latest")
            return
        if box.clickedButton() is not install:
            return
        self.busy = True
        self.window.update_button.setEnabled(False)
        self.window.update_button.setText("다운로드 중…")

        def work():
            try:
                installer = download(release, self.progress.emit)
            except Exception as error:
                self.downloaded.emit(None, error)
            else:
                self.downloaded.emit(installer, None)

        Thread(target=work, daemon=True).start()

    def on_progress(self, value):
        self.window.update_button.setText(f"다운로드 {value}%")

    def on_downloaded(self, installer, error):
        self.busy = False
        self.window.update_button.setEnabled(True)
        self.window.update_button.setText(f"{self.release.version} 업데이트")
        if error:
            self.window.error("업데이트 다운로드", error)
            return
        if not self.window.confirm_close_documents():
            installer.unlink(missing_ok=True)
            return
        try:
            launch_setup(installer)
        except OSError as error:
            installer.unlink(missing_ok=True)
            self.window.error("업데이트 설치", error)
            return
        self.window.closing_for_update = True
        self.window.close()

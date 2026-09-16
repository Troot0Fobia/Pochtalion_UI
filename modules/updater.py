import asyncio
import hashlib
import json
import os
import shutil
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from core.logger import setup_logger
from core.paths import REPO, UPDATES, VERSION

LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = b"Pochtalion-Updater"


def _parse_version(raw: str) -> tuple[int, ...]:
    return tuple(int(p) for p in raw.strip().lstrip("vV").split("."))


def _asset_name(version: str) -> str:
    if sys.platform.startswith("win"):
        return f"Pochtalion-{version}-windows-setup.exe"
    if os.environ.get("APPIMAGE"):
        return f"Pochtalion-{version}-linux-x86_64.AppImage"
    return f"Pochtalion-{version}-linux-x86_64.tar.gz"


def _await_reply(reply: QNetworkReply) -> asyncio.Future:
    fut = asyncio.get_running_loop().create_future()
    reply.finished.connect(lambda: not fut.done() and fut.set_result(None))
    return fut


class Updater:

    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.logger = setup_logger("Pochtalion.Updater", "updater.log")
        self._manager = QNetworkAccessManager()

    async def start(self) -> None:
        if not REPO:
            self.logger.info("Update checking disabled: no repo configured at build time")
            return
        try:
            release = await self.check_for_update()
        except Exception:
            self.logger.warning("Update check failed", exc_info=True)
            return
        if release is not None:
            self._show_update_prompt(release)

    def _request(self, url: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        # GitHub asset downloads (and, less often, the API itself) redirect -
        # Qt does not follow redirects unless told to.
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        return request

    async def _fetch_bytes(self, url: str) -> bytes | None:
        reply = self._manager.get(self._request(url))
        await _await_reply(reply)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.logger.warning("GET %s failed: %s", url, reply.errorString())
                return None
            return bytes(reply.readAll())
        finally:
            reply.deleteLater()

    async def check_for_update(self) -> dict | None:
        data = await self._fetch_bytes(LATEST_RELEASE_URL)
        if data is None:
            return None
        try:
            release = json.loads(data)
        except json.JSONDecodeError:
            self.logger.warning("Update check: GitHub API returned non-JSON body")
            return None

        if release.get("draft") or release.get("prerelease"):
            return None

        tag = release.get("tag_name", "")
        try:
            latest = _parse_version(tag)
            current = _parse_version(VERSION)
        except ValueError:
            self.logger.warning("Update check: unparsable version %r", tag)
            return None

        if latest <= current:
            return None

        self.logger.info("Update available: %s -> %s", VERSION, tag)
        return release

    def _show_update_prompt(self, release: dict) -> None:
        tag = release.get("tag_name", "")
        notes = (release.get("body") or "").strip()

        box = QMessageBox(self.main_window)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Доступно обновление")
        box.setText(f"Вышла новая версия Pochtalion {tag.lstrip('vV')}. Обновить сейчас?")
        if notes:
            box.setDetailedText(notes)
        update_btn = box.addButton("Обновить сейчас", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        box.setModal(False)

        def _on_clicked(button):
            if button is update_btn:
                asyncio.create_task(self._download_update(release))
            box.deleteLater()

        box.buttonClicked.connect(_on_clicked)
        box.show()

    async def _download_update(self, release: dict) -> None:
        version = release.get("tag_name", "").lstrip("vV")
        asset_name = _asset_name(version)
        assets = {a.get("name"): a for a in release.get("assets", [])}

        asset = assets.get(asset_name)
        sha_asset = assets.get(f"{asset_name}.sha256")
        if asset is None or sha_asset is None:
            self.main_window.show_notification(
                "Обновление", f"В релизе {release.get('tag_name')} не найден файл {asset_name}"
            )
            self.logger.error("Update asset %s missing from release %s", asset_name, release.get("tag_name"))
            return

        # Drop anything left over from a previous, never-applied download so
        # UPDATES doesn't accumulate multiple large binaries over time.
        shutil.rmtree(UPDATES, ignore_errors=True)
        UPDATES.mkdir(parents=True, exist_ok=True)
        dest = UPDATES / asset_name

        progress = QProgressDialog(
            f"Скачивание Pochtalion {version}...", "Отмена", 0, 0, self.main_window
        )
        progress.setWindowTitle("Обновление Pochtalion")
        progress.setMinimumDuration(0)
        progress.setModal(False)
        progress.show()

        try:
            if not await self._download_file(asset["browser_download_url"], dest, progress):
                return

            progress.setLabelText("Проверка контрольной суммы...")
            sha_bytes = await self._fetch_bytes(sha_asset["browser_download_url"])
            if sha_bytes is None:
                self._fail_download(dest, "Не удалось скачать контрольную сумму")
                return

            expected = sha_bytes.decode("utf-8", "ignore").split()[0].lower()
            actual = await self._sha256_file(dest)
            if actual != expected:
                self.logger.error(
                    "Update checksum mismatch for %s: expected %s, got %s", asset_name, expected, actual
                )
                self._fail_download(dest, "Контрольная сумма скачанного файла не совпадает")
                return

            self.logger.info("Update %s downloaded and verified: %s", version, dest)
            self.main_window.show_notification(
                "Обновление", f"Версия {version} скачана и проверена: {dest.name}"
            )
        finally:
            progress.close()

    def _fail_download(self, dest, message: str) -> None:
        dest.unlink(missing_ok=True)
        self.main_window.show_notification("Обновление", message)

    async def _download_file(self, url: str, dest, progress: QProgressDialog) -> bool:
        reply = self._manager.get(self._request(url))
        cancelled = False

        def _on_ready_read():
            f.write(bytes(reply.readAll()))

        def _on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setMaximum(total)
                progress.setValue(received)

        def _on_canceled() -> None:
            nonlocal cancelled
            cancelled = True
            reply.abort()

        with dest.open("wb") as f:
            reply.readyRead.connect(_on_ready_read)
            reply.downloadProgress.connect(_on_progress)
            progress.canceled.connect(_on_canceled)
            await _await_reply(reply)

        try:
            if cancelled:
                dest.unlink(missing_ok=True)
                return False
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.logger.error("Update download failed: %s", reply.errorString())
                self._fail_download(dest, f"Ошибка скачивания: {reply.errorString()}")
                return False
            return True
        finally:
            reply.deleteLater()

    async def _sha256_file(self, path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
                # Yield between chunks so hashing a few-hundred-MB file doesn't
                # stall the Qt/asyncio loop for the couple of seconds it takes -
                # there is no thread pool in this app to offload onto instead.
                await asyncio.sleep(0)
        return digest.hexdigest()

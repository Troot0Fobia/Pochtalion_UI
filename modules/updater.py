import asyncio
import hashlib
import json
import re
import shutil
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from core.logger import setup_logger
from core.paths import DATA_DIR, INSTALL_FORM, REPO, UPDATES, VERSION
from modules import update_apply

LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = b"Pochtalion-Updater"

# One asset per install form, matching exactly what build-linux.sh /
# build-windows.ps1 produce. REPO is empty (update checking disabled) in
# dev mode by default, but a developer can still populate the gitignored
# REPO file locally to test the check/download flow from source - "dev"
# is treated like "directory" below so that doesn't crash; update_apply
# still correctly refuses to actually apply anything in dev mode.
_ASSET_SUFFIX_BY_FORM = {
    "appimage": "linux-x86_64.AppImage",
    "directory": None,  # platform-dependent, see _asset_name()
    "windows-installer": "windows-setup.exe",
}


def _parse_version(raw: str) -> tuple[int, ...]:
    return tuple(int(p) for p in raw.strip().lstrip("vV").split("."))


def _verified_marker(dest):
    # Sidecar recording the hash `dest` was last confirmed to match, so a
    # cached download doesn't need re-hashing (multi-second, unindicated) on
    # every subsequent startup it sits around unapplied.
    return dest.with_name(dest.name + ".verified")


_VERSIONED_NAME_RE = re.compile(r"^Pochtalion-(\d+\.\d+\.\d+)-")


def _cleanup_stale_updates() -> None:
    """Drop anything in UPDATES that isn't for a version still ahead of the
    one currently running: the downloaded asset + its .verified marker for
    an update that's already been applied (we're now running it or newer),
    and non-versioned debris (helper_output.log, a leftover staging/
    extraction, a helper copy from a previous failed apply attempt) that
    has no reason to survive once nothing pending references it."""
    if not UPDATES.is_dir():
        return
    try:
        current = _parse_version(VERSION)
    except ValueError:
        return
    for entry in UPDATES.iterdir():
        match = _VERSIONED_NAME_RE.match(entry.name)
        if match:
            try:
                if _parse_version(match.group(1)) > current:
                    continue  # still a pending, not-yet-applied update
            except ValueError:
                pass
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            # E.g. helper_output.log can still be held open for a moment by
            # the just-exited helper process (it relaunches the app and only
            # *then* closes/deletes itself, so there's a real race with the
            # new instance's own startup) - skip it for now, next launch's
            # cleanup will get it once it's no longer locked. Must not abort
            # the rest of this loop over one stuck entry.
            pass


def _asset_name(version: str) -> str:
    if INSTALL_FORM in ("directory", "dev"):
        suffix = "windows-x86_64.zip" if sys.platform.startswith("win") else "linux-x86_64.tar.gz"
    else:
        suffix = _ASSET_SUFFIX_BY_FORM[INSTALL_FORM]
    return f"Pochtalion-{version}-{suffix}"


def _await_reply(reply: QNetworkReply) -> asyncio.Future:
    fut = asyncio.get_running_loop().create_future()
    reply.finished.connect(lambda: not fut.done() and fut.set_result(None))
    return fut


class Updater:

    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.logger = setup_logger("Pochtalion.Updater", "updater.log")
        self._manager = QNetworkAccessManager()

    async def start(self, manual: bool = False) -> None:
        """manual=True is a user-triggered "check for updates" click: unlike
        the silent startup check, it always reports back (disabled / up to
        date / checked and failed), not just when there's something to do."""
        try:
            _cleanup_stale_updates()
        except Exception:
            self.logger.warning("Stale update cleanup failed", exc_info=True)
        if not REPO:
            if manual:
                self.main_window.show_notification(
                    "Обновление", "Проверка обновлений отключена в этой сборке"
                )
            else:
                self.logger.info("Update checking disabled: no repo configured at build time")
            return
        try:
            release = await self.check_for_update()
            if release is None:
                if manual:
                    self.main_window.show_notification(
                        "Обновление", f"Установлена последняя версия ({VERSION})"
                    )
                return
            await self._offer_update(release)
        except Exception:
            self.logger.exception("Update check/offer failed")
            if manual:
                self.main_window.show_notification("Обновление", "Не удалось проверить обновления")

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

    def _resolve_assets(self, release: dict) -> tuple[str, dict, dict] | None:
        """Look up the asset (+ its .sha256 sidecar) this install form/platform
        needs from a release's asset list. None (with the user already
        notified) if the release doesn't have one."""
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
            return None
        return asset_name, asset, sha_asset

    async def _offer_update(self, release: dict) -> None:
        """A newer version exists. If it's already downloaded and verified
        from a previous session (UPDATES persists across restarts, unlike
        TMP), skip straight to "ready to apply" instead of re-downloading -
        otherwise fall back to the normal "update now?" prompt."""
        resolved = self._resolve_assets(release)
        if resolved is None:
            return
        asset_name, _asset, sha_asset = resolved
        version = release.get("tag_name", "").lstrip("vV")
        dest = UPDATES / asset_name

        if dest.exists():
            sha_bytes = await self._fetch_bytes(sha_asset["browser_download_url"])
            expected = sha_bytes.decode("utf-8", "ignore").split()[0].lower() if sha_bytes else None
            if expected:
                marker = _verified_marker(dest)
                # Re-hashing a few-hundred-MB file on every single startup this
                # sits around unapplied is a multi-second, entirely invisible
                # stall (no progress dialog, unlike the download itself) - once
                # it's been hashed and matched once, trust that instead of
                # doing it again every launch. Falls back to a real hash if the
                # marker is missing/stale (first time seeing this file, or an
                # older build that never wrote one).
                if marker.exists() and marker.read_text().strip() == expected:
                    self.logger.info("Reusing already-verified update %s (cached checksum): %s", version, dest)
                    await self._finish_apply(version, dest)
                    return
                if await self._sha256_file(dest) == expected:
                    marker.write_text(expected)
                    self.logger.info("Reusing already-downloaded update %s: %s", version, dest)
                    await self._finish_apply(version, dest)
                    return
            self.logger.info("Cached download %s is stale/unverifiable, will re-download", dest)

        self._show_update_prompt(release)

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
        resolved = self._resolve_assets(release)
        if resolved is None:
            return
        asset_name, asset, sha_asset = resolved
        version = release.get("tag_name", "").lstrip("vV")

        # Drop anything left over from a previous download so UPDATES doesn't
        # accumulate multiple large binaries over time. _offer_update() has
        # already ruled out this exact asset being a reusable cached copy by
        # the time we get here.
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

            _verified_marker(dest).write_text(expected)
            self.logger.info("Update %s downloaded and verified: %s", version, dest)
        finally:
            progress.close()

        await self._finish_apply(version, dest)

    async def _finish_apply(self, version: str, dest) -> None:
        try:
            apply_args = await update_apply.prepare(dest, DATA_DIR)
        except Exception:
            self.logger.exception("Update apply preparation failed")
            self._fail_download(dest, "Обновление скачано, но не может быть применено на этой установке")
            return
        self._show_restart_prompt(version, apply_args)

    def _fail_download(self, dest, message: str) -> None:
        dest.unlink(missing_ok=True)
        self.main_window.show_notification("Обновление", message)

    def _show_restart_prompt(self, version: str, apply_args: dict) -> None:
        box = QMessageBox(self.main_window)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Обновление готово")
        box.setText(
            f"Версия {version} скачана и проверена. Перезапустить сейчас, чтобы применить обновление?"
        )
        restart_btn = box.addButton("Перезапустить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        box.setModal(False)

        def _on_clicked(button):
            if button is restart_btn:
                # Anything raised here escapes straight into Qt's C++ signal
                # dispatch with no Python frame above to catch it - PyQt6 has
                # already been seen to hard-abort the whole process for that
                # (not just print and continue), leaving nothing in our own
                # logs. Catch and log explicitly instead of relying on that.
                try:
                    update_apply.launch_and_exit(apply_args)
                except Exception:
                    self.logger.exception("Failed to launch update apply helper")
                    self.main_window.show_notification(
                        "Обновление", "Не удалось запустить применение обновления"
                    )
                else:
                    self.main_window.close()
            box.deleteLater()

        box.buttonClicked.connect(_on_clicked)
        box.show()

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
            try:
                await _await_reply(reply)
            finally:
                # progress outlives this function (the caller reuses it for the
                # checksum step, then closes it) - QProgressDialog.close() always
                # re-emits canceled() even on a normal, non-cancel close, so this
                # stale connection must not still be live for that later close()
                # to call reply.abort() on a reply we're about to delete.
                progress.canceled.disconnect(_on_canceled)

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

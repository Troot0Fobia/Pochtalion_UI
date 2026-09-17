"""Prevents two Pochtalion processes from sharing the same DATA_DIR at once.

Two instances writing to the same database.db / entity_cache.json / session
files at the same time is a corruption risk, not just a UX nuisance. The lock
is scoped to DATA_DIR (not the whole machine) so two independent portable
copies of the app in different folders are still free to run side by side -
consistent with how MODE/DATA_DIR already separate them (see core/paths.py).

Built on QLocalServer/QLocalSocket rather than a lockfile because it comes
free with PyQt6 (no new dependency / lock-file regeneration) and cleans up
after a crash the same way on every platform: a stale server left behind by a
killed process answers no one, so removeServer() + a fresh listen() reclaims
it automatically.
"""

import hashlib

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from core.paths import DATA_DIR

_SERVER_NAME = "Pochtalion-" + hashlib.sha1(str(DATA_DIR.resolve()).encode()).hexdigest()[:16]


def try_acquire() -> QLocalServer | None:
    """Returns a live QLocalServer if no other instance holds this DATA_DIR's
    lock, or None if one already does. The caller must keep the returned
    server referenced for the app's lifetime - it releases the lock as soon
    as it's garbage collected or closed."""
    probe = QLocalSocket()
    probe.connectToServer(_SERVER_NAME)
    is_running = probe.waitForConnected(200)
    probe.close()
    if is_running:
        return None

    QLocalServer.removeServer(_SERVER_NAME)
    server = QLocalServer()
    server.listen(_SERVER_NAME)
    return server

from io import BytesIO
import qrcode
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class QRLoginWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Telethon QR Login")
        self.setMinimumSize(420, 520)

        self.title = QLabel(
            "Отсканируй QR в Telegram на телефоне:\nSettings → Devices → Link Desktop Device"
        )
        self.title.setWordWrap(True)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status = QLabel("Статус: ожидаю QR…")
        self.status.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.qr_label, 1)
        layout.addWidget(self.status)
        self.setLayout(layout)
        self.show()

    def update_status(self, text: str):
        self.status.setText(text)

    def fill_qr(self, url: str):
        pixmap = self._qr_pixmap_from_url(url)
        self.qr_label.setPixmap(pixmap)

    def _qr_pixmap_from_url(self, url: str) -> QPixmap:
        qr = qrcode.QRCode(
            version=None,
            box_size=8,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        qimage = QImage.fromData(buf.getvalue(), "PNG")

        return QPixmap.fromImage(qimage)

    def exit(self):
        self.close()

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)


class VideoDialog(QDialog):

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Видео")
        self.setModal(False)
        self.resize(800, 600)

        self.video_path = Path(video_path.replace("../", "")).resolve()
        if not self.video_path.exists():
            raise FileNotFoundError(f"{self.video_path} not found")

        self.player = QMediaPlayer(parent)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)

        # --- Controls ---
        self.play_btn = QPushButton("▶")
        self.play_btn.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.seek)

        self.time_label = QLabel("00:00 / 00:00")

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.audio.setVolume)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.close)

        # --- Layout ---
        controls = QHBoxLayout()
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider)
        controls.addWidget(self.time_label)
        controls.addWidget(QLabel("🔊"))
        controls.addWidget(self.volume_slider)
        controls.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.video_widget)
        layout.addLayout(controls)

        # --- Events ---
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)

        # --- Start playback ---
        self.player.setSource(QUrl.fromLocalFile(str(self.video_path)))
        self.player.play()
        self.is_playing = True

    def toggle_play(self):
        if self.is_playing:
            self.player.pause()
            self.play_btn.setText("▶")
        else:
            self.player.play()
            self.play_btn.setText("⏸")
        self.is_playing = not self.is_playing

    def update_position(self, position):
        self.slider.setValue(position)
        self.time_label.setText(
            self.format_time(position)
            + " / "
            + self.format_time(self.player.duration())
        )

    def update_duration(self, duration):
        self.slider.setRange(0, duration)

    def seek(self, pos):
        self.player.setPosition(pos)

    def format_time(self, ms):
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02}:{seconds:02}"

    def closeEvent(self, event):
        # if self.player:
        #     # self.player.stop()
        #     self.player.deleteLater()
        event.accept()


from PyQt6.QtWidgets import QMessageBox, QPushButton


class ConfirmDelete(QMessageBox):

    def __init__(self):
        super().__init__()

        self.res_value = -1
        self.setWindowTitle("Pochtalion_UI")
        self.setText("Вы хотите удалить привязанных пользователей к этой сессии?")
        self.setIcon(QMessageBox.Icon.Question)

        if btn_all := QPushButton("Удалить всех"):
            btn_all.clicked.connect(self.on_all)
            self.addButton(btn_all, QMessageBox.ButtonRole.ActionRole)

        if btn_sended := QPushButton("Удалить отправленных"):
            btn_sended.clicked.connect(self.on_sended)
            self.addButton(btn_sended, QMessageBox.ButtonRole.ActionRole)

        if btn_not_sended := QPushButton("Удалить не отправленных"):
            btn_not_sended.clicked.connect(self.on_not_sended)
            self.addButton(btn_not_sended, QMessageBox.ButtonRole.ActionRole)

        if btn_no := QPushButton("Нет"):
            btn_no.clicked.connect(self.on_no)
            self.addButton(btn_no, QMessageBox.ButtonRole.ActionRole)

        if btn_cancel := QPushButton("Отмена"):
            btn_cancel.clicked.connect(self.on_cancel)
            self.addButton(btn_cancel, QMessageBox.ButtonRole.RejectRole)

        self.setDefaultButton(btn_all)
        self.setEscapeButton(btn_cancel)

    def on_all(self):
        self.res_value = 1
        self.accept()

    def on_sended(self):
        self.res_value = 2
        self.accept()

    def on_not_sended(self):
        self.res_value = 3
        self.accept()

    def on_no(self):
        self.res_value = 0
        self.accept()

    def on_cancel(self):
        self.reject()

    @staticmethod
    def ask():
        box = ConfirmDelete()
        box.exec()
        return box.res_value

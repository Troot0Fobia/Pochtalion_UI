from PyQt6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout
)
from PyQt6.QtCore import Qt

class AuthWindow(QDialog):
    def __init__(self, parent, session_file):
        super().__init__(parent)
        self.setWindowTitle("Авторизация Telegram")
        self.setModal(True)
        self.setFixedWidth(300)

        self.main_title = QLabel(f"Активация аккаунта {session_file}")

        self.phone_label = QLabel("Введине номер телефона:")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+XXXXXXXXXX")

        self.code_label = QLabel("Введите код из Telegram:")
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("XXXXX")
        self.code_label.hide()
        self.code_input.hide()

        self.password_label = QLabel("Введите пароль 2FA:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("**********")
        self.password_label.hide()
        self.password_input.hide()

        self.ok_button = QPushButton("Отправить")
        self.cancel_button = QPushButton("Отмена")

        self.ok_button.clicked.connect(self._on_send_clicked)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.main_title)
        layout.addWidget(self.phone_label)
        layout.addWidget(self.phone_input)
        layout.addWidget(self.code_label)
        layout.addWidget(self.code_input)
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_input)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.ok_button)
        btn_layout.addWidget(self.cancel_button)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.state = "phone"
        self.future = None
        self._result = None


    def next_step(self, step):
        if step == "code": 
            self.state = "code"
            self.phone_input.setDisabled(True)
            self.code_label.show()
            self.code_input.show()
        elif step == "password":
            self.state = "password"
            self.code_input.setDisabled(True)
            self.password_label.show()
            self.password_input.show()

    
    def _on_send_clicked(self):
        if self.state == "phone":
            self._result = self.phone_input.text().strip()
        elif self.state == "code":
            self._result = self.code_input.text().strip()
        elif self.state == "password":
            self._result = self.password_input.text().strip()
        if self.future:
            self.future.set_result(self._result)


    def _on_cancel_clicked(self):
        if self.future:
            self.future.set_result(None)
        self.close()


    async def get_input_async(self):
        import asyncio
        self.future = asyncio.get_event_loop().create_future()
        self.show()
        return await self.future

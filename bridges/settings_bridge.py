from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow
from qasync import asyncSlot

from .base_bridge import BaseBridge
import datetime
import base64
import puremagic
import shutil
import json
import uuid
import asyncio
from core.paths import SMM_IMAGES, SESSIONS, USERS_DATA, PROFILE_PHOTOS


class SettingsBridge(BaseBridge):
    renderSettingsSessions = pyqtSignal(str)
    renderSMMMessages = pyqtSignal(str)
    renderChooseSessions = pyqtSignal(str)
    renderParsingProgressData = pyqtSignal(str)
    renderMailingProgressData = pyqtSignal(str)
    finishParsing = pyqtSignal()
    finishMailing = pyqtSignal()
    sessionChangedState = pyqtSignal(str, str)
    renderSettings = pyqtSignal(str)

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)


    @asyncSlot()
    async def loadSettingsSessions(self):
        sessions = await self.database.get_sessions()
        active_sessions = {}
        session_manager = self.main_window.session_manager
        if session_manager is not None:
            active_sessions = session_manager.get_active_sessions()
        for s in sessions:
            s['file_exists'] = (SESSIONS / s['session_file']).exists()
            s['status'] = active_sessions.get(s['session_file'], 0)

        self.renderSettingsSessions.emit(json.dumps(sessions))


    @asyncSlot(str, str, str)
    async def saveSession(self, fileName, base64data, phone_number):
        if not fileName and not base64data:
            fileName = f"{int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())}_telethon.session"
            open(SESSIONS / fileName, "a").close()
        else:
            with open(str(SESSIONS / fileName), 'wb') as f:
                f.write(base64.b64decode(base64data))

        session_id = await self.database.add_new_session(fileName)
        session = {"session_id": session_id, "is_active": 1, "session_file": fileName, 'status': 0}
        if not self.main_window.active_session:
            self.main_window.active_session = session
        json_session = json.dumps([session])
        self.renderSettingsSessions.emit(json_session)
        self.sidebar_bridge.renderSelectSessions.emit(json_session)
        if phone_number:
            session_manager = self.main_window.session_manager
            if session_manager is None:
                return
            await session_manager.start_session(session_id, fileName, phone_number)


    @asyncSlot(str, str)
    async def deleteSession(self, session_id_str, session_name):
        session_manager = self.main_window.session_manager
        if session_manager is not None:
            await session_manager.stop_session(session_name)
        session_id = int(session_id_str)
        user_ids = await self.database.delete_session(session_id)
        try:
            (SESSIONS / session_name).unlink(missing_ok=True)
            for user_id in user_ids:
                shutil.rmtree(USERS_DATA / f"{user_id}_{session_name}", ignore_errors=True)
            shutil.rmtree(PROFILE_PHOTOS / session_name, ignore_errors=True)
            self.sidebar_bridge.deleteSessionFromSelect.emit(session_id_str)
        except Exception as e:
            self.logger.error(f"{self.__class__.__name__}\tError while deleting session {session_name}", exc_info=True)


    @asyncSlot()
    async def loadSMM(self):
        smm_messages = await self.database.get_smm_messages()
        self.renderSMMMessages.emit(json.dumps(smm_messages))


    @asyncSlot(str)
    async def addNewSMMMessage(self, newSMMMessage_str):
        newSMMMessage = json.loads(newSMMMessage_str)
        filename = None
        if newSMMMessage['photo']:
            filename = f"{uuid.uuid4().hex}{puremagic.ext_from_filename(newSMMMessage['filename'])}"
            with open(str(SMM_IMAGES / filename), 'wb') as f:
                f.write(base64.b64decode(newSMMMessage['photo']))

        smm_id = await self.database.add_smm_message(newSMMMessage['text'], filename)
        self.renderSMMMessages.emit(json.dumps([{"id": smm_id, "text": newSMMMessage['text'], "photo": filename}]))


    @asyncSlot(str)
    async def deleteSMMMessage(self, smm_message_id_str):
        smm_message_id = int(smm_message_id_str)
        filename = await self.database.delete_smm_message(smm_message_id)
        if filename:
            (SMM_IMAGES / filename).unlink(missing_ok=True)


    @asyncSlot(str)
    async def saveChanges(self, editedSMM_str):
        editedSMM = json.loads(editedSMM_str)
        filename = None
        if editedSMM['photo']:
            filename = f"{uuid.uuid4().hex}{puremagic.ext_from_filename(editedSMM['filename'])}"
            with open(str(SMM_IMAGES / filename), 'wb') as f:
                f.write(base64.b64decode(editedSMM['photo']))

        old_photo = await self.database.edit_smm_message(int(editedSMM['id']), editedSMM['text'], filename)
        if editedSMM['photo'] and old_photo:
            (SMM_IMAGES / old_photo).unlink(missing_ok=True)


    @asyncSlot()
    async def loadChooseSessions(self):
        sessions = await self.database.get_sessions()
        if not sessions:
            self.main_window.show_notification("Внимание", "Нет загруженных сессий")
            return
        self.renderChooseSessions.emit(json.dumps(sessions))
        

    @asyncSlot(str)
    async def startSession(self, session_str):
        session_manager = self.main_window.session_manager
        if session_manager is None:
            return
        session = json.loads(session_str)
        await session_manager.start_session(session['session_id'], session['session_name'])

    
    @asyncSlot(str)
    async def stopSession(self, session_file):
        session_manager = self.main_window.session_manager
        if session_manager is None:
            return
        await session_manager.stop_session(session_file)


    @asyncSlot(str)
    async def startParsing(self, parse_data_str):
        if self.main_window.mailer.running:
            return
        # await self.main_window.parser.start(parse_data_str)
        
        self.parsing_task = asyncio.create_task(self.main_window.parser.start(parse_data_str))


    @asyncSlot()
    async def stopParsing(self):
        if self.parsing_task:
            self.parsing_task.cancel()
            try:
                await self.parsing_task
            except asyncio.CancelledError:
                pass
        await self.main_window.parser.stop()
    
    @pyqtSlot(str)
    def show_notification(self, message):
        self.main_window.show_notification("Внимание", message)


    @asyncSlot(str)
    async def saveParsedData(self, save_type):
        if save_type == 'db':
            await self.main_window.parser.save_to_db()
        elif save_type == 'csv':
            await self.main_window.parser.export_csv()

    
    @asyncSlot(str)
    async def startMailing(self, mail_data_str):
        if self.main_window.parser.running:
            return
        self.mailing_task = asyncio.create_task(self.main_window.mailer.start(mail_data_str))


    @asyncSlot()
    async def stopMailing(self):
        if self.mailing_task:
            self.mailing_task.cancel()
            try:
                await self.mailing_task
            except asyncio.CancelledError:
                pass
        await self.main_window.mailer.stop()


    @pyqtSlot()
    def loadSettings(self):
        settings = self.main_window.settings_manager.get_settings()
        self.renderSettings.emit(json.dumps(settings))


    @pyqtSlot(str)
    def changeSettings(self, setting_str):
        setting = json.loads(setting_str)
        self.main_window.settings_manager.update_settings(setting['key'], setting['value'])


    @pyqtSlot()
    def resetSettings(self):
        self.main_window.settings_manager.reset_defaults()
        self.loadSettings()


    @asyncSlot()
    async def refreshSessionManager(self):
        if self.main_window.settings_manager.get_setting('api_keys'):
            await self.main_window.refreshSessionManager()
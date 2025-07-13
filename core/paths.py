from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS = ROOT_DIR / 'assets'
USERS_DATA = ASSETS / 'users_data'
PROFILE_PHOTOS = ASSETS / 'profile_photos'
SMM_IMAGES = ASSETS / 'smm_images'
SESSIONS = ASSETS / 'sessions'
LOGS = ROOT_DIR / 'logs'
TMP = ROOT_DIR / 'tmp'
DATABASE = ROOT_DIR / 'database'
WEB = ROOT_DIR / 'web'
SETTINGS = ROOT_DIR / 'settings'
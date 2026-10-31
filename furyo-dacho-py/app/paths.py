"""アプリのフォルダの場所（このファイルの2つ上がアプリ本体のフォルダ）"""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS_DIR = os.path.join(APP_DIR, 'views')
LIB_DIR = os.path.join(APP_DIR, 'lib')
DATABASE_DIR = os.path.join(APP_DIR, 'database')

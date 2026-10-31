#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初回セットアップ（PHP版 setup.php に相当）。!!! 完了後は必ずサーバーから削除すること !!!"""
import os
import sys

# ------------------------------------------------------------
# APP_DIR: アプリ本体（app/ views/ lib/ config/ を含むフォルダ）の場所。
# 公開フォルダ（public_html）とアプリ本体を分けて置く場合は、
# ここをサーバー上の実際のパスに書き換える。
#   例: APP_DIR = '/virtual/アカウント名/furyo-dacho'
# アプリ一式をそのまま置く構成では変更不要。
# ------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, APP_DIR)
from wsgiref.handlers import CGIHandler  # noqa: E402

from app.maintenance.setup import application  # noqa: E402

CGIHandler().run(application)

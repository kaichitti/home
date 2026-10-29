"""モデルの共通部分（DB 接続を受け取って保持する）"""


class BaseModel:
    table = ''

    def __init__(self, db):
        self.db = db

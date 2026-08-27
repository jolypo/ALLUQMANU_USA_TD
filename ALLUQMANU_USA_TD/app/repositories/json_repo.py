import json
from pathlib import Path
from threading import Lock
from app.config import settings


class JsonRepository:
    def __init__(self, name: str):
        self.path=Path(settings.data_path)/name
        self.lock=Lock()
        if not self.path.exists(): self.path.write_text("[]",encoding="utf-8")
    def all(self):
        with self.lock:
            try: return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception: return []
    def append(self,item:dict):
        with self.lock:
            data=self.all_unlocked(); data.append(item); self.path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    def all_unlocked(self):
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception: return []
    def replace(self,data:list[dict]):
        with self.lock: self.path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

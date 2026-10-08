"""생성기 사이에서 검증된 자료를 공유한다. HTML을 다시 해석하지 않는다."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def save(kind, data, root=None):
    path = Path(root or ROOT) / 'dashboard/overview-input' / (kind + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    part.replace(path)

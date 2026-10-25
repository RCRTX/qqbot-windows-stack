"""用户明确指定的角色原图；只读独立副本，不依赖临时附件路径。"""
from pathlib import Path
from typing import NamedTuple, Optional
import hashlib
import json


REFERENCE_PATH = Path(__file__).resolve().parents[3] / "data/character_reference/self.jpg"
CORRECTIONS_PATH = REFERENCE_PATH.parent / "image_corrections.json"
CORRECTION_LABEL = "\n【用户对此图的解释（非独立识别）】"


class CharacterReference(NamedTuple):
    image_bytes: bytes
    sha256: str
    image_format: str


def load_character_reference(path: Path = REFERENCE_PATH) -> Optional[CharacterReference]:
    """每次按实际内容摘要，参考替换会使既有描述版本失效。"""
    try:
        image_bytes = path.read_bytes()
    except FileNotFoundError:
        return None
    if not image_bytes.startswith(b"\xff\xd8\xff"):
        raise ValueError("角色参考必须为有效 JPEG 文件")
    return CharacterReference(image_bytes, hashlib.sha256(image_bytes).hexdigest(), "jpeg")


def load_image_corrections(path: Path = CORRECTIONS_PATH) -> dict:
    """只接受明确来自用户的按图纠正，不构造通用规则。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("图片纠正索引必须为对象")
    return data


def image_corrections_fingerprint() -> str:
    return hashlib.sha256(json.dumps(load_image_corrections(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def append_image_correction(image_hash: str, description: str, *, corrections: Optional[dict] = None) -> str:
    """仅在读出边界附加来源；不把用户答案送回识别或关联模型。"""
    if not description:
        return description
    base = description.split(CORRECTION_LABEL, 1)[0]
    entry = (load_image_corrections() if corrections is None else corrections).get(image_hash)
    if not isinstance(entry, dict) or entry.get("source") != "user":
        return base
    explanation = entry.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return base
    return base + CORRECTION_LABEL + explanation.strip()

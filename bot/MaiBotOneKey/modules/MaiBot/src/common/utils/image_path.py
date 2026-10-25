from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class StoredImagePathError(ValueError):
    """图片存储路径不在项目目录内。"""


def normalize_stored_separators(stored_path: str | Path) -> str:
    """把存储路径里的 Windows 反斜杠统一换成正斜杠。

    ⚠️ 2026-09-23 事故修复（别删）：数据库里的路径是**写入时那个系统**的写法。
    本机旧库是在 Windows 上攒的（`data\\images\\x.png`，实测 1082/1116 行都是反斜杠），
    搬到 Linux 跑时反斜杠会被当成文件名的普通字符 → `exists()` 认为每个文件都丢了
    → 表情包完整性检查会把这些记录当"破损注册记录"删掉。
    Windows 和 POSIX 都接受正斜杠，所以这里统一换掉（`serialize_stored_image_path`
    写侧本来就产出 as_posix，两边口径一致）。
    """
    return str(stored_path).replace("\\", "/")


def resolve_stored_image_path(stored_path: str | Path) -> Path:
    """将数据库中的图片路径解析为项目内的真实路径。"""
    if not str(stored_path).strip():
        raise StoredImagePathError("图片路径不能为空")
    path = Path(normalize_stored_separators(stored_path))
    resolved_path = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    try:
        resolved_path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise StoredImagePathError(f"图片路径不在项目目录内: {stored_path}") from exc
    return resolved_path


def serialize_stored_image_path(file_path: str | Path) -> str:
    """将项目内图片路径序列化为相对项目根目录的存储路径。"""
    if not str(file_path).strip():
        raise StoredImagePathError("图片路径不能为空")
    resolved_path = Path(file_path).resolve()
    try:
        return resolved_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as exc:
        raise StoredImagePathError(f"图片路径不在项目目录内: {file_path}") from exc


def stored_image_paths_equal(left: str | Path, right: str | Path) -> bool:
    """按项目内真实路径语义比较两个图片存储路径。"""
    return resolve_stored_image_path(left) == resolve_stored_image_path(right)

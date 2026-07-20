# -*- coding: utf-8 -*-
"""图片路径安全解析：把 /imges/<...> 解析为图片根目录内的真实路径，越界即拒绝。

用于修复 image-thumb / 图片删除 / 按图搜索 等处的路径穿越（含 Windows 盘符、UNC、内嵌 ..）。
"""
import os


def resolve_within_imges(url_path: str, image_root: str) -> str:
    """将形如 ``/imges/xxx`` 的 URL 路径解析为 ``image_root`` 下的真实绝对路径。

    用 realpath + commonpath 做包含性校验，可拦截 ``..``、Windows 绝对路径（``C:/...``）、
    UNC（``//host/share``）等一切越界写法。越界或非法一律抛 ``ValueError``。
    """
    if not isinstance(url_path, str) or not url_path.startswith("/imges/"):
        raise ValueError("路径必须以 /imges/ 开头")
    rel = url_path.split("/imges/", 1)[1].lstrip("/\\")
    root = os.path.realpath(image_root)
    target = os.path.realpath(os.path.join(root, rel))
    try:
        within = os.path.commonpath([root, target]) == root
    except ValueError:
        # 不同盘符（Windows）会让 commonpath 抛错 —— 即越界
        within = False
    if not within:
        raise ValueError("路径越出图片根目录")
    return target

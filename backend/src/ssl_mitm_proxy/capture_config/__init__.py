# -*- coding: utf-8 -*-
"""MITM 抓包响应文件配置包。

原单文件 ``capture_config.py`` 已按业务域拆分；``__init__`` 重新导出全部公开符号，
保持 ``from ...ssl_mitm_proxy.capture_config import X`` 旧导入不变。

- ``_core``：路径 / session marker / 请求目标解析 / 原子读写 / item_id 规范化
- ``on_sale`` / ``orders`` / ``purchases`` / ``todos`` / ``notifications``：各业务域响应文件读写
"""

from ._core import *  # noqa: F401,F403
from .on_sale import *  # noqa: F401,F403
from .orders import *  # noqa: F401,F403
from .purchases import *  # noqa: F401,F403
from .todos import *  # noqa: F401,F403
from .notifications import *  # noqa: F401,F403

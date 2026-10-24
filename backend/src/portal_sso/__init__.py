# -*- coding: utf-8 -*-
"""门户（D:\\Project\\Portal）单点登录：门户当 OIDC 提供方，本系统当客户端。

- settings.py  配置（系统设置 → 系统关联 · 门户单点登录）
- flow.py      授权码 + PKCE 流程、id_token 校验、一次性票
- identity.py  门户身份 → 本系统用户（按 sub 认人，首次按用户名匹配，没有就新建）

HTTP 端点在 use_web/sso（公开，登录用）与 use_web/system（管理员，配置用）。
"""

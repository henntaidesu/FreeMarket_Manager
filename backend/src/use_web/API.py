# -*- coding: utf-8 -*-
"""
use_web V2 API 聚合模块（按前端页面归类）

层级蓝图注册：
- 从 src/API.py 接收前缀 /mercariV2/src
- 向下传递给各资源模块，添加 /use_web/<page> 路径段
- 完整 URL 格式: /mercariV2/src/use_web/<page>/<endpoint>

页面归类：
- login           前端 /login 页（含启动种子管理员事件）
- inventory       前端 /inventory 页（含 ocr/scan 辅助识别）
- orders          前端 /orders 页
- on_sale_items   前端 /on-sale-items 页
- transactions    前端 /transactions 页
- mercari_accounts  前端 /mercari-accounts 页
- product_type_category_mappings  前端 /product-type-category-mappings 页
- system          前端 /system 页（一级 + 二级：cost_records/cost_expenses/warehouses/categories）
- web_drive       跨页面共享的浏览器自动化基础设施
"""

from fastapi import APIRouter, Depends

from ..auth import require_auth

from .login.API import router as login_router
from .system.API import router as system_router
from .product_types.API import router as product_types_router
from .web_drive.API import router as web_drive_router
from .on_sale_items.API import router as on_sale_items_router
from .orders.API import router as orders_router
from .inventory.API import router as inventory_router
from .inventory.API import public_router as inventory_public_router
from .mercari_accounts.API import router as mercari_accounts_router
from .todos.API import router as todos_router
from .tasks.API import router as tasks_router
from .notifications.API import router as notifications_router
from .memos.API import router as memos_router
from .talk_scripts.API import router as talk_scripts_router
from .gotion.API import router as gotion_router
from .mercari_image.API import public_router as mercari_image_public_router

router = APIRouter(prefix="/use_web")

# ============ 公开端点（无需认证） ============
# 登录页：login 端点 + 启动种子事件
router.include_router(login_router, prefix="/login", tags=["login"])
# 库存公开缩略图
router.include_router(inventory_public_router, prefix="/inventory", tags=["inventory-public"])
# 煤炉图片代理（跨页面共享，前端 <img> 直接通过 URL 访问，无需 token）
router.include_router(mercari_image_public_router, tags=["mercari-image"])

# ============ 需要认证的端点 ============
_AUTH = [Depends(require_auth)]

# 系统管理（含 6 个二级页面：cost-records / cost-expenses / warehouses / categories / transactions / product-type-category-mappings）
router.include_router(system_router, prefix="/system", tags=["system"], dependencies=_AUTH)
router.include_router(product_types_router, prefix="/product-types", tags=["product-types"], dependencies=_AUTH)
router.include_router(web_drive_router, prefix="/web-drive", tags=["web-drive"], dependencies=_AUTH)
router.include_router(on_sale_items_router, prefix="/on-sale-items", tags=["on-sale-items"], dependencies=_AUTH)
router.include_router(orders_router, prefix="/orders", tags=["orders"], dependencies=_AUTH)
router.include_router(inventory_router, prefix="/inventory", tags=["inventory"], dependencies=_AUTH)
router.include_router(mercari_accounts_router, prefix="/mercari-accounts", tags=["mercari-accounts"], dependencies=_AUTH)
router.include_router(todos_router, prefix="/todos", tags=["todos"], dependencies=_AUTH)
# 任务队列：出品/同步/改价等重型操作的统一提交入口与状态查询
router.include_router(tasks_router, prefix="/tasks", tags=["tasks"], dependencies=_AUTH)
router.include_router(notifications_router, prefix="/notifications", tags=["notifications"], dependencies=_AUTH)
router.include_router(memos_router, prefix="/memos", tags=["memos"], dependencies=_AUTH)
router.include_router(talk_scripts_router, prefix="/talk-scripts", tags=["talk-scripts"], dependencies=_AUTH)
router.include_router(gotion_router, prefix="/gotion", tags=["gotion"], dependencies=_AUTH)

# -*- coding: utf-8 -*-
"""系统管理 API 模块（对应前端 /system 页面 + 4 个二级页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/system
- 完整 URL 示例:
    POST /mercariV2/src/use_web/system/restart
    GET  /mercariV2/src/use_web/system/cost-records
    GET  /mercariV2/src/use_web/system/warehouses

聚合：
- 一级：系统重启 + 用户管理 + 出品默认值 + SSL MITM 代理控制
- 二级：cost_records / cost_expenses / warehouses / categories
"""

from fastapi import APIRouter, Depends

from ...auth import require_admin
from .units.system_handler import RestartOut, restart_system

# 仅管理员可调用的危险端点依赖（重启、数据库切换/迁移/备份、MITM 控制、清日志）
_ADMIN = [Depends(require_admin)]
from .units.users_handler import list_users, create_user, change_password
from .units.app_config_handler import (
    ListingDefaultsOut,
    get_listing_defaults,
    put_listing_defaults,
    MgmtCipherModeOut,
    get_mgmt_cipher_mode,
    put_mgmt_cipher_mode,
)
from .units.ai_config_handler import (
    DeepSeekConfigOut,
    get_deepseek_config,
    put_deepseek_config,
)
from .units.printer_config_handler import (
    PrinterParams,
    get_printer_params,
    put_printer_params,
)
from .units.system_log_handler import (
    list_system_logs,
    clear_system_logs,
    create_operation_log,
)
from .units.ssl_mitm_handler import (
    download_ca_cert,
    get_last_capture,
    get_status,
    post_start,
    post_stop,
)
from .units.db_admin_handler import (
    DbConfigOut,
    TestResult,
    SwitchOut,
    HotSwitchOut,
    get_database_config,
    test_mysql_connection,
    switch_database,
    migrate_database,
    hot_switch_mysql_database,
    backup_database,
)

# 二级子模块 router
from .cost_records.API import router as cost_records_router
from .cost_expenses.API import router as cost_expenses_router
from .warehouses.API import router as warehouses_router
from .categories.API import router as categories_router
from .transactions.API import router as transactions_router
from .product_type_category_mappings.API import router as ptcm_router
from .yahoo_category_mappings.API import router as yahoo_ycm_router
from .settlement.API import router as settlement_router

router = APIRouter()

# ===== 一级端点：系统主页 =====
# 系统重启（仅管理员）
router.add_api_route("/restart", restart_system, methods=["POST"], response_model=RestartOut, dependencies=_ADMIN)

# 用户管理（System 页面"用户管理"区）
router.add_api_route("/users", list_users, methods=["GET"])
router.add_api_route("/users", create_user, methods=["POST"])
router.add_api_route("/change-password", change_password, methods=["POST"])

# 应用配置（出品默认值）
router.add_api_route("/listing-defaults", get_listing_defaults, methods=["GET"], response_model=ListingDefaultsOut)
router.add_api_route("/listing-defaults", put_listing_defaults, methods=["PUT"], response_model=ListingDefaultsOut)
router.add_api_route("/printer-params", get_printer_params, methods=["GET"], response_model=PrinterParams)
router.add_api_route("/printer-params", put_printer_params, methods=["PUT"], response_model=PrinterParams)

# 管理番号暗号编码模式（隐藏页 /x9 切换：二进制 ◇◆ / 五进制 -=~<>）
router.add_api_route("/mgmt-cipher-mode", get_mgmt_cipher_mode, methods=["GET"], response_model=MgmtCipherModeOut)
router.add_api_route("/mgmt-cipher-mode", put_mgmt_cipher_mode, methods=["PUT"], response_model=MgmtCipherModeOut)

# 系统配置（DeepSeek AI：API Key / 模型 / API 地址）
router.add_api_route("/deepseek-config", get_deepseek_config, methods=["GET"], response_model=DeepSeekConfigOut)
router.add_api_route("/deepseek-config", put_deepseek_config, methods=["PUT"], response_model=DeepSeekConfigOut)

# 系统日志（自动上架 / 自动获取 / 操作日志）
router.add_api_route("/system-logs", list_system_logs, methods=["GET"])
router.add_api_route("/system-logs/clear", clear_system_logs, methods=["POST"], dependencies=_ADMIN)
# 操作日志上报（前端提示统一写入，记录登录用户）
router.add_api_route("/operation-logs", create_operation_log, methods=["POST"])

# 数据库管理（SQLite / MySQL 切换 + 数据迁移）——除只读 config 外均限管理员
router.add_api_route("/database/config", get_database_config, methods=["GET"], response_model=DbConfigOut)
router.add_api_route("/database/test-connection", test_mysql_connection, methods=["POST"], response_model=TestResult, dependencies=_ADMIN)
router.add_api_route("/database/switch", switch_database, methods=["POST"], response_model=SwitchOut, dependencies=_ADMIN)
router.add_api_route("/database/migrate", migrate_database, methods=["POST"], response_model=SwitchOut, dependencies=_ADMIN)
# MySQL 数据库热切换（同服务器切库：测试库 ⇄ 正式库，无需重启）
router.add_api_route("/database/hot-switch", hot_switch_mysql_database, methods=["POST"], response_model=HotSwitchOut, dependencies=_ADMIN)
# 数据库备份（当前库整库覆盖到目标 MySQL，可能较久，放宽超时）
router.add_api_route("/database/backup", backup_database, methods=["POST"], response_model=SwitchOut, dependencies=_ADMIN)

# SSL MITM 代理控制（start/stop 限管理员）
router.add_api_route("/ssl-mitm/status", get_status, methods=["GET"])
router.add_api_route("/ssl-mitm/start", post_start, methods=["POST"], dependencies=_ADMIN)
router.add_api_route("/ssl-mitm/stop", post_stop, methods=["POST"], dependencies=_ADMIN)
router.add_api_route("/ssl-mitm/ca-cert", download_ca_cert, methods=["GET"])
router.add_api_route("/ssl-mitm/last-capture", get_last_capture, methods=["GET"])

# ===== 二级页面（嵌套到 /system 下） =====
router.include_router(cost_records_router, prefix="/cost-records", tags=["cost-records"])
router.include_router(cost_expenses_router, prefix="/cost-expenses", tags=["cost-expenses"])
router.include_router(warehouses_router, prefix="/warehouses", tags=["warehouses"])
router.include_router(categories_router, prefix="/categories", tags=["categories"])
router.include_router(transactions_router, prefix="/transactions", tags=["transactions"])
router.include_router(
    ptcm_router,
    prefix="/product-type-category-mappings",
    tags=["product-type-category-mappings"],
)
router.include_router(
    yahoo_ycm_router,
    prefix="/yahoo-category-mappings",
    tags=["yahoo-category-mappings"],
)
router.include_router(settlement_router, prefix="/settlement", tags=["settlement"])

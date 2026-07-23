# -*- coding: utf-8 -*-
"""表模型包 —— 按前端页面分类到子文件夹后，在此聚合重新导出，
保持 ``from ..models import XxxModel`` 等旧导入不变。"""

from .system.category import CategoryModel
from .system.warehouse import WarehouseModel
from .system.product_type import ProductTypeModel
from .system.transaction import TransactionModel
from .system.user import UserModel
from .system.cost_record import CostRecordModel
from .system.cost_expense import CostExpenseModel
from .system.settlement_record import SettlementRecordModel
from .system.product_type_category_mapping import ProductTypeCategoryMappingModel
from .system.config_entry import ConfigEntryModel
from .system.talk_script import TalkScriptModel
from .system.system_log import SystemLogModel
from .system.task_queue import TaskQueueModel
from .inventory.inventory import InventoryModel
from .inventory.image_embedding import ImageEmbeddingModel
from .orders.order import OrderModel
from .orders.order_outbound_line import OrderOutboundLineModel
from .on_sale_items.on_sale_item import OnSaleItemModel
from .todos.todo_item import TodoItemModel
from .todos.transaction_message import TransactionMessageModel
from .notifications.notification import NotificationModel
from .notifications.bundle_purchase_request import BundlePurchaseRequestModel
from .notifications.desired_price_offer import DesiredPriceOfferModel
from .mercari_accounts.mercari_account import MercariAccountModel
from .memos.memo import MemoModel
from .gotion.gotion_table import GotionTableModel
from .gotion.gotion_column import GotionColumnModel
from .gotion.gotion_row import GotionRowModel

__all__ = [
    'CategoryModel',
    'WarehouseModel',
    'ProductTypeModel',
    'InventoryModel',
    'TransactionModel',
    'UserModel',
    'CostRecordModel',
    'CostExpenseModel',
    'SettlementRecordModel',
    'OrderModel',
    'MercariAccountModel',
    'OnSaleItemModel',
    'OrderOutboundLineModel',
    'ProductTypeCategoryMappingModel',
    'ConfigEntryModel',
    'TodoItemModel',
    'TransactionMessageModel',
    'NotificationModel',
    'BundlePurchaseRequestModel',
    'DesiredPriceOfferModel',
    'MemoModel',
    'TalkScriptModel',
    'SystemLogModel',
    'TaskQueueModel',
    'GotionTableModel',
    'GotionColumnModel',
    'GotionRowModel',
    'ImageEmbeddingModel',
]

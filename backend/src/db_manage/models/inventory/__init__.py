# -*- coding: utf-8 -*-
"""库存管理页相关表模型。"""

from .inventory import InventoryModel
from .image_embedding import ImageEmbeddingModel
from .image_hash import ImageHashModel
from .inventory_batch import InventoryBatchModel
from .inventory_old import InventoryOldModel, InventoryBatchOldModel
from .inbound_shipment import InboundShipmentModel
from .inbound_shipment_line import InboundShipmentLineModel
from .inbound_receipt import InboundReceiptModel
from .inventory_manual_outbound import InventoryManualOutboundModel
from .inventory_series import InventorySeriesModel
from .inventory_series_item import InventorySeriesItemModel

__all__ = ["InventoryModel", "ImageEmbeddingModel", "ImageHashModel", "InventoryBatchModel",
           "InventoryOldModel", "InventoryBatchOldModel", "InboundShipmentModel", "InboundShipmentLineModel", "InboundReceiptModel", "InventoryManualOutboundModel",
           "InventorySeriesModel", "InventorySeriesItemModel"]

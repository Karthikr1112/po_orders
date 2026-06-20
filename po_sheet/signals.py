from decimal import Decimal
from django.db import models
from django.db.models import Sum, F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .models import PurchaseOrder, PurchaseOrderItem

def _recalculate_po_totals(po):
    """Recalculate and save all aggregate totals on a PurchaseOrder."""
    po_items = po.items.all()
    if po_items.exists():
        agg = po_items.aggregate(
            total_qty=Sum("tot_qty"),
            grand_total=Sum("tot_amt"),
        )
        po.total_quantity = agg["total_qty"] or 0
        po.grand_total = agg["grand_total"] or Decimal("0")
    else:
        po.total_quantity = 0
        po.grand_total = Decimal("0")

    po.save(
        update_fields=[
            "total_quantity",
            "grand_total",
        ]
    )

@receiver(post_save, sender=PurchaseOrderItem)
def update_po_totals_on_item_save(sender, instance, **kwargs):
    _recalculate_po_totals(instance.purchase_order)

@receiver(post_delete, sender=PurchaseOrderItem)
def update_po_totals_on_item_delete(sender, instance, **kwargs):
    _recalculate_po_totals(instance.purchase_order)

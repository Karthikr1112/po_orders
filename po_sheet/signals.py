from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PurchaseOrder, PurchaseOrderItem


def _recalculate_po_totals(po_id: int) -> None:
    """
    Recalculate and persist aggregate totals for a PurchaseOrder.

    Accepts the PK instead of the instance so this function is safe to call
    inside transaction.on_commit (where the original instance may be stale).
    Uses update() rather than save() to avoid triggering further signals and
    to touch only the two aggregate columns.
    """
    agg = PurchaseOrderItem.objects.filter(purchase_order_id=po_id).aggregate(
        total_qty=Sum("tot_qty"),
        grand_total=Sum("tot_amt"),
    )
    PurchaseOrder.objects.filter(pk=po_id).update(
        total_quantity=agg["total_qty"] or 0,
        grand_total=agg["grand_total"] or Decimal("0"),
    )


@receiver(post_save, sender=PurchaseOrderItem)
def update_po_totals_on_item_save(sender, instance, **kwargs):
    po_id = instance.purchase_order_id
    # Defer until the current transaction commits so the new row is visible
    # to the aggregate query (avoids double-counting on nested saves).
    transaction.on_commit(lambda: _recalculate_po_totals(po_id))


@receiver(post_delete, sender=PurchaseOrderItem)
def update_po_totals_on_item_delete(sender, instance, **kwargs):
    po_id = instance.purchase_order_id
    transaction.on_commit(lambda: _recalculate_po_totals(po_id))

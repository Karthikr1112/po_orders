"""
Production hardening migration.

Changes:
  - PurchaseOrder: larger grand_total precision (12→14), 3 composite indexes,
    is_draft db_index
  - PurchaseOrderItem: larger tot_amt precision (12→14), new updated_at field,
    discount_percentage validators (DB-level: no change), composite index,
    ITEM_TYPE_CHOICES (metadata only)
  - Vendor: vendor_name index
  - AdminBudget: larger approved_amount precision (12→14), new updated_at field
  - SubCategory: ch4_code db_index
"""

from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("po_sheet", "0012_alter_subcategory_unique_together_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ------------------------------------------------------------------ #
        # PurchaseOrder                                                        #
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name="purchaseorder",
            name="grand_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddIndex(
            model_name="purchaseorder",
            index=models.Index(
                fields=["created_by", "is_draft", "-created_at"],
                name="po_user_draft_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseorder",
            index=models.Index(
                fields=["is_draft", "-created_at"],
                name="po_draft_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseorder",
            index=models.Index(
                fields=["vendor", "is_draft"],
                name="po_vendor_draft_idx",
            ),
        ),
        # ------------------------------------------------------------------ #
        # PurchaseOrderItem                                                    #
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name="purchaseorderitem",
            name="tot_amt",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="purchaseorderitem",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddIndex(
            model_name="purchaseorderitem",
            index=models.Index(
                fields=["subcategory", "purchase_order"],
                name="poi_subcat_po_idx",
            ),
        ),
        # ------------------------------------------------------------------ #
        # Vendor                                                              #
        # ------------------------------------------------------------------ #
        migrations.AddIndex(
            model_name="vendor",
            index=models.Index(
                fields=["vendor_name"],
                name="vendor_name_idx",
            ),
        ),
        # ------------------------------------------------------------------ #
        # AdminBudget                                                          #
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name="adminbudget",
            name="approved_amount",
            field=models.DecimalField(decimal_places=2, max_digits=14),
        ),
        migrations.AddField(
            model_name="adminbudget",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # ------------------------------------------------------------------ #
        # SubCategory                                                          #
        # ------------------------------------------------------------------ #
        migrations.AlterField(
            model_name="subcategory",
            name="ch4_code",
            field=models.CharField(
                blank=True, db_index=True, max_length=50, null=True
            ),
        ),
    ]

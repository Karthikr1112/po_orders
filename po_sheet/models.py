from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Vendor(models.Model):
    vendor_code = models.CharField(max_length=50, primary_key=True)
    vendor_name = models.CharField(max_length=200, db_index=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    gst_number = models.CharField(max_length=50, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    pin_code = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        verbose_name = "Vendor"
        verbose_name_plural = "Vendors"
        indexes = [
            models.Index(fields=["vendor_name"], name="vendor_name_idx"),
            models.Index(fields=["city"], name="vendor_city_idx"),
        ]

    def __str__(self):
        return f"{self.vendor_code} - {self.vendor_name}"


class Buyer(models.Model):
    # unique=True implicitly creates a B-tree index on name
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Buyer"
        verbose_name_plural = "Buyers"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Season(models.Model):
    # unique=True implicitly creates a B-tree index on name
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    # unique=True implicitly creates a B-tree index on name
    name = models.CharField(max_length=100, unique=True)
    ch4_code = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    buyers = models.ManyToManyField(Buyer, related_name="subcategories", blank=True)

    class Meta:
        verbose_name = "Sub-Category"
        verbose_name_plural = "Sub-Categories"

    def __str__(self):
        return self.name


class SubCategorySize(models.Model):
    # ForeignKey auto-creates a B-tree index on subcategory_id
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.CASCADE, related_name="sizes"
    )
    name = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Sub-Category Size"
        verbose_name_plural = "Sub-Category Sizes"
        unique_together = [("subcategory", "name")]

    def __str__(self):
        return f"{self.subcategory.name} - {self.name}"


class PurchaseOrder(models.Model):
    PO_TYPE_CHOICES = [
        ("Fresh", "Fresh"),
        ("Stock", "Stock"),
        ("Promo", "Promo"),
        ("Sample", "Sample"),
    ]

    # unique=True on po_number gives us the lookup index for free
    po_number = models.CharField(max_length=50, unique=True, db_index=True)
    po_date = models.DateField(blank=True, null=True)
    po_type = models.CharField(
        max_length=50, blank=True, null=True, choices=PO_TYPE_CHOICES
    )
    # db_index on season enables the (season, is_draft) compound index below
    season = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    # ForeignKey auto-creates index on buyer_id
    buyer = models.ForeignKey(
        Buyer, on_delete=models.SET_NULL, null=True, blank=True
    )
    agent = models.CharField(max_length=100, blank=True, null=True)
    # ForeignKey auto-creates index on vendor_id
    vendor = models.ForeignKey(
        Vendor, on_delete=models.PROTECT, null=True, blank=True
    )
    ratio_type = models.ForeignKey(
        "RatioType", on_delete=models.SET_NULL, null=True, blank=True
    )
    is_draft = models.BooleanField(default=True, db_index=True)
    delivery_schedules = models.JSONField(default=list, blank=True, null=True)
    notes = models.TextField(blank=True)

    # Denormalised aggregates kept in sync by signals — avoids SUM on every page load
    total_quantity = models.IntegerField(default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ["-created_at"]
        indexes = [
            # Draft PO lookup per user (most frequent: po_sheet view)
            models.Index(
                fields=["created_by", "is_draft", "-created_at"],
                name="po_user_draft_date_idx",
            ),
            # All submitted POs ordered by date (staff all_records view)
            models.Index(
                fields=["is_draft", "-created_at"],
                name="po_draft_date_idx",
            ),
            # Vendor PO lookup
            models.Index(fields=["vendor", "is_draft"], name="po_vendor_draft_idx"),
            # Budget calculation: base_items filtered by buyer + is_draft
            models.Index(fields=["buyer", "is_draft"], name="po_buyer_draft_idx"),
            # Budget calculation: base_items filtered by season + is_draft
            models.Index(fields=["season", "is_draft"], name="po_season_draft_idx"),
        ]

    def __str__(self):
        return self.po_number

    @property
    def total_items(self):
        return self.total_quantity

    @property
    def subtotal(self):
        return self.grand_total


class PurchaseOrderItem(models.Model):
    ITEM_TYPE_CHOICES = [
        ("Fresh", "Fresh"),
        ("Stock", "Stock"),
        ("Promo", "Promo"),
        ("Sample", "Sample"),
    ]

    # ForeignKey auto-creates index on purchase_order_id
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    # db_index=True is redundant with the compound index below but explicit for FK joins
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.PROTECT, db_index=True
    )
    item_type = models.CharField(
        max_length=50, default="Fresh", choices=ITEM_TYPE_CHOICES
    )
    order_qty = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    # tot_qty mirrors order_qty; stored so budget reports can aggregate without a join
    tot_qty = models.IntegerField(default=0)
    tot_amt = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    size_allocations = models.JSONField(default=dict, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Purchase Order Item"
        verbose_name_plural = "Purchase Order Items"
        indexes = [
            # Budget aggregate: GROUP BY subcategory WHERE purchase_order IN (...)
            models.Index(
                fields=["subcategory", "purchase_order"],
                name="poi_subcat_po_idx",
            ),
            # Reverse direction: items belonging to a PO, ordered by subcategory
            models.Index(
                fields=["purchase_order", "subcategory"],
                name="poi_po_subcat_idx",
            ),
        ]

    def __str__(self):
        return f"{self.purchase_order_id} — {self.subcategory_id}"

    def save(self, *args, **kwargs):
        self.tot_qty = self.order_qty
        discount_factor = Decimal("1") - (
            Decimal(str(self.discount_percentage)) / Decimal("100")
        )
        self.tot_amt = self.unit_price * Decimal(self.tot_qty) * discount_factor
        super().save(*args, **kwargs)


class SubCategoryPriceRange(models.Model):
    # ForeignKey auto-creates index on subcategory_id.
    # The unique_together below creates a compound index on
    # (subcategory_id, season_id, sales_from_range, sales_to_range) which also
    # serves as a covering prefix for filter(subcategory=sc) queries.
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.CASCADE, related_name="price_ranges"
    )
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="price_ranges", null=True, blank=True
    )
    sales_from_range = models.DecimalField(max_digits=12, decimal_places=2)
    sales_to_range = models.DecimalField(max_digits=12, decimal_places=2)
    buying_from_range = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    buying_to_range = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    approved_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    approved_quantity = models.PositiveIntegerField(default=0)
    subcat_code = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = "SubCategory Price Range"
        verbose_name_plural = "SubCategory Price Ranges"
        # Creates compound index (subcategory_id, season_id, sales_from_range, sales_to_range)
        unique_together = [("subcategory", "season", "sales_from_range", "sales_to_range")]

    def __str__(self):
        return (
            f"{self.subcategory.name} | "
            f"Sales: {self.sales_from_range}–{self.sales_to_range} | "
            f"Buying: {self.buying_from_range}–{self.buying_to_range}"
        )


class RatioType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Ratio Type"
        verbose_name_plural = "Ratio Types"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubCategoryRatio(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="ratios", null=True, blank=True)
    buyer = models.ForeignKey(Buyer, on_delete=models.CASCADE, related_name="ratios", null=True, blank=True)
    subcategory = models.ForeignKey(SubCategory, on_delete=models.CASCADE, related_name="ratios")
    ratio_type = models.ForeignKey(RatioType, on_delete=models.CASCADE, related_name="ratios", null=True, blank=True)
    ratio_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sub-Category Ratio"
        verbose_name_plural = "Sub-Category Ratios"
        unique_together = [("vendor", "buyer", "subcategory", "ratio_type")]

    def __str__(self):
        v_name = self.vendor.vendor_name if self.vendor else "All Vendors"
        b_name = self.buyer.name if self.buyer else "All Buyers"
        t_name = self.ratio_type.name if self.ratio_type else "Default"
        return f"{v_name} - {b_name} - {self.subcategory.name} ({t_name})"



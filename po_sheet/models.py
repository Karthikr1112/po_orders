from django.db import models
from django.contrib.auth.models import User

# 1. Vendor
class Vendor(models.Model):
    vendor_code = models.CharField(max_length=50, primary_key=True)
    vendor_name = models.CharField(max_length=200)
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

    def __str__(self):
        return f"{self.vendor_code} - {self.vendor_name}"

# 2. Buyer (for Buyer Name dropdown)
class Buyer(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Buyer"
        verbose_name_plural = "Buyers"
        ordering = ["name"]

    def __str__(self):
        return self.name

class Season(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
        ordering = ["name"]

    def __str__(self):
        return self.name

# 4. SubCategory
class SubCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    ch4_code = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "Sub-Category"
        verbose_name_plural = "Sub-Categories"

    def __str__(self):
        return self.name

class SubCategorySize(models.Model):
    subcategory = models.ForeignKey(SubCategory, on_delete=models.CASCADE, related_name="sizes")
    name = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Sub-Category Size"
        verbose_name_plural = "Sub-Category Sizes"
        unique_together = [("subcategory", "name")]

    def __str__(self):
        return f"{self.subcategory.name} - {self.name}"

# 5. PurchaseOrder
class PurchaseOrder(models.Model):
    po_number = models.CharField(max_length=50, unique=True)
    po_date = models.DateField(blank=True, null=True)
    po_type = models.CharField(max_length=50, blank=True, null=True) # Fresh, Stock, Promo, Sample
    season = models.CharField(max_length=100, blank=True, null=True) # Season / Name
    buyer = models.ForeignKey(Buyer, on_delete=models.SET_NULL, null=True, blank=True)
    agent = models.CharField(max_length=100, blank=True, null=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, null=True, blank=True)
    is_draft = models.BooleanField(default=True)
    delivery_schedules = models.JSONField(default=list, blank=True, null=True)
    notes = models.TextField(blank=True) # Remarks
    
    total_quantity = models.IntegerField(default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="purchase_orders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ["-created_at"]

    def __str__(self):
        return self.po_number

    @property
    def total_items(self):
        return self.total_quantity

    @property
    def subtotal(self):
        return self.grand_total

# 6. PurchaseOrderItem
class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    subcategory = models.ForeignKey(SubCategory, on_delete=models.PROTECT)
    item_type = models.CharField(max_length=50, default="Fresh")
    order_qty = models.IntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tot_qty = models.IntegerField(default=0)
    tot_amt = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    size_allocations = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        verbose_name = "Purchase Order Item"
        verbose_name_plural = "Purchase Order Items"

    def __str__(self):
        return f"{self.purchase_order.po_number} - {self.subcategory.name}"

    def save(self, *args, **kwargs):
        from decimal import Decimal
        self.tot_qty = self.order_qty
        discount_factor = Decimal('1') - (Decimal(str(self.discount_percentage)) / Decimal('100'))
        self.tot_amt = self.unit_price * self.tot_qty * discount_factor
        super().save(*args, **kwargs)

# 7. AdminBudget
class AdminBudget(models.Model):
    subcategory = models.OneToOneField(SubCategory, on_delete=models.CASCADE, related_name="budget")
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approved_budgets")
    approved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Admin Budget"
        verbose_name_plural = "Admin Budgets"

    def __str__(self):
        return f"Budget — {self.subcategory.name}"

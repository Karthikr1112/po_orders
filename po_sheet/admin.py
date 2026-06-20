from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    AdminBudget,
    SubCategorySize,
    PurchaseOrder,
    PurchaseOrderItem,
    SubCategory,
    Vendor,
    Buyer,
    Season,
)

# Register Season
@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

# Register Buyer
@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

# Register Vendor
@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("vendor_code", "vendor_name", "city", "email", "phone")
    search_fields = ("vendor_code", "vendor_name")
    list_filter = ("city",)

class SubCategorySizeInline(admin.TabularInline):
    model = SubCategorySize
    extra = 1

# Register SubCategory
@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ("ch4_code", "name", "display_sizes")
    search_fields = ("name", "ch4_code")
    inlines = [SubCategorySizeInline]

    def display_sizes(self, obj):
        return ", ".join([s.name for s in obj.sizes.all()])
    display_sizes.short_description = "Sizes"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('sizes')

class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    fields = (
        "subcategory",
        "item_type",
        "order_qty",
        "unit_price",
        "discount_percentage",
        "tot_qty",
        "tot_amt",
    )
    readonly_fields = ("tot_qty", "tot_amt")

@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "po_number",
        "po_date",
        "po_type",
        "season",
        "buyer",
        "agent",
        "vendor",
        "is_draft",
        "total_quantity",
        "grand_total",
        "created_by",
        "created_at",
    )
    search_fields = ("po_number", "season", "buyer__name", "agent", "vendor__vendor_name")
    list_filter = ("is_draft", "po_date", "po_type")
    readonly_fields = ("total_quantity", "grand_total", "created_at", "updated_at")
    inlines = [PurchaseOrderItemInline]

@admin.register(AdminBudget)
class AdminBudgetAdmin(admin.ModelAdmin):
    list_display = ("subcategory", "approved_amount", "approved_by", "approved_at")
    search_fields = ("subcategory__name",)
    list_filter = ("approved_at", "approved_by")
    readonly_fields = ("approved_at",)

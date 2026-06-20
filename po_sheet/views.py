import csv
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import AdminBudgetForm
from .models import (
    AdminBudget,
    Buyer,
    PurchaseOrder,
    PurchaseOrderItem,
    Season,
    SubCategory,
    SubCategorySize,
    Vendor,
)

logger = logging.getLogger("po_sheet")


# ---------------------------------------------------------------------------
# MSSQL helpers
# ---------------------------------------------------------------------------

def _get_mssql_conn():
    """Open a fresh pyodbc connection from settings. Always close in a finally block."""
    from django.conf import settings
    import pyodbc

    db = settings.DATABASES["mssql"]
    driver = db.get("OPTIONS", {}).get("driver", "ODBC Driver 17 for SQL Server")
    server = db.get("HOST", "localhost")
    port = db.get("PORT", "")
    server_str = f"{server},{port}" if port else server
    conn_str = (
        f"DRIVER={{{driver}}};SERVER={server_str};"
        f"DATABASE={db.get('NAME','')};UID={db.get('USER','')};PWD={db.get('PASSWORD','')}"
    )
    return pyodbc.connect(conn_str, timeout=10)


def fetch_mssql_vendors(query=None):
    vendors_list = []
    conn = None
    try:
        conn = _get_mssql_conn()
        cursor = conn.cursor()
        if query:
            like_val = f"%{query}%"
            cursor.execute(
                "SELECT TOP 100 lifnr, name, city, gstNo, postCode, street, email1"
                " FROM [dbo].[Vendor_B]"
                " WHERE lifnr LIKE ? OR name LIKE ? OR city LIKE ?",
                (like_val, like_val, like_val),
            )
        else:
            cursor.execute(
                "SELECT TOP 50 lifnr, name, city, gstNo, postCode, street, email1"
                " FROM [dbo].[Vendor_B]"
            )
        for row in cursor.fetchall():
            vendors_list.append({
                "vendor_code": row[0],
                "vendor_name": row[1] or "",
                "address": row[5] or "",
                "city": row[2] or "",
                "state": "",
                "pin_code": str(row[4]) if row[4] is not None else "",
                "email": row[6] or "",
                "phone": "",
                "gst_number": row[3] or "",
                "contact_person": "",
            })
    except Exception:
        logger.exception("MSSQL error in fetch_mssql_vendors")
    finally:
        if conn:
            conn.close()
    return vendors_list


def get_or_create_mssql_vendor(vendor_code):
    if not vendor_code:
        return None
    vendor_code = str(vendor_code).strip()

    local = Vendor.objects.filter(vendor_code=vendor_code).first()
    if local:
        return local

    conn = None
    try:
        conn = _get_mssql_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, city, gstNo, postCode, street, email1"
            " FROM [dbo].[Vendor_B] WHERE lifnr = ?",
            (vendor_code,),
        )
        row = cursor.fetchone()
        if row:
            vendor, _ = Vendor.objects.get_or_create(
                vendor_code=vendor_code,
                defaults={
                    "vendor_name": row[0] or vendor_code,
                    "city": row[1] or "",
                    "gst_number": row[2] or "",
                    "pin_code": str(row[3]) if row[3] is not None else "",
                    "address": row[4] or "",
                    "email": row[5] or "",
                    "state": "",
                    "phone": "",
                    "contact_person": "",
                },
            )
            return vendor
    except Exception:
        logger.exception("MSSQL error in get_or_create_mssql_vendor: %s", vendor_code)
    finally:
        if conn:
            conn.close()

    # Fallback: create a stub vendor so the PO can still be saved
    vendor, _ = Vendor.objects.get_or_create(
        vendor_code=vendor_code,
        defaults={"vendor_name": vendor_code},
    )
    return vendor


# ---------------------------------------------------------------------------
# Budget helpers
# ---------------------------------------------------------------------------

def get_subcategory_remaining_budget(subcategory, exclude_po_id=None, include_draft_po_id=None):
    if not subcategory:
        return Decimal("0")
    try:
        budget = subcategory.budget
    except AdminBudget.DoesNotExist:
        return Decimal("0")
    if not budget:
        return Decimal("0")

    qs = PurchaseOrderItem.objects.filter(
        subcategory=subcategory,
        purchase_order__is_draft=False,
    )
    if exclude_po_id:
        qs = qs.exclude(purchase_order_id=exclude_po_id)

    spent = qs.aggregate(total=Sum("tot_amt"))["total"] or Decimal("0")

    if include_draft_po_id:
        draft_spent = (
            PurchaseOrderItem.objects.filter(
                purchase_order_id=include_draft_po_id,
                purchase_order__is_draft=True,
                subcategory=subcategory,
            ).aggregate(total=Sum("tot_amt"))["total"]
            or Decimal("0")
        )
        spent += draft_spent

    return budget.approved_amount - spent


# ---------------------------------------------------------------------------
# PO number generation  (race-safe: unique constraint is the final guard)
# ---------------------------------------------------------------------------

def generate_next_po_number():
    last = (
        PurchaseOrder.objects.filter(po_number__regex=r"^PO-\d+$")
        .order_by("-id")
        .values_list("po_number", flat=True)
        .first()
    )
    if last:
        m = re.search(r"(\d+)$", last)
        next_num = int(m.group(1)) + 1 if m else 1
    else:
        next_num = 1
    return f"PO-{next_num:04d}"


# ---------------------------------------------------------------------------
# PO totals helper  (used inline where on_commit is too late for the response)
# ---------------------------------------------------------------------------

def _refresh_po_totals(po):
    agg = po.items.aggregate(total_qty=Sum("tot_qty"), grand_total=Sum("tot_amt"))
    PurchaseOrder.objects.filter(pk=po.pk).update(
        total_quantity=agg["total_qty"] or 0,
        grand_total=agg["grand_total"] or Decimal("0"),
    )
    po.total_quantity = agg["total_qty"] or 0
    po.grand_total = agg["grand_total"] or Decimal("0")


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect("po_sheet")
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", "").strip(),
            password=request.POST.get("password", ""),
        )
        if user is not None:
            login(request, user)
            return redirect("po_sheet")
        messages.error(request, "Invalid username or password")
    return render(request, "po_sheet/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# ---------------------------------------------------------------------------
# Main PO sheet
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
def po_sheet(request):
    user = request.user
    po = PurchaseOrder.objects.filter(created_by=user, is_draft=True).first()
    if not po:
        po = PurchaseOrder.objects.create(
            created_by=user,
            is_draft=True,
            po_number=generate_next_po_number(),
        )

    # Ensure draft has a proper PO-XXXX number
    if not re.match(r"^PO-\d{4,}$", po.po_number):
        po.po_number = generate_next_po_number()
        po.save(update_fields=["po_number"])

    po_items = po.items.select_related("subcategory").all()

    agg = po_items.aggregate(total_qty=Sum("tot_qty"), grand_total=Sum("tot_amt"))
    totals = {
        "items": agg["total_qty"] or 0,
        "subtotal": Decimal("0"),
        "grand_total": agg["grand_total"] or Decimal("0"),
    }

    # Keep stored totals in sync (cheap: only 2 columns)
    PurchaseOrder.objects.filter(pk=po.pk).update(
        total_quantity=totals["items"],
        grand_total=totals["grand_total"],
    )

    # Budget availability per subcategory for items already on the draft
    placed_map = {
        row["subcategory_id"]: row["total"]
        for row in PurchaseOrderItem.objects.filter(purchase_order__is_draft=False)
        .values("subcategory_id")
        .annotate(total=Sum("tot_amt"))
    }
    for item in po_items:
        sc = item.subcategory
        try:
            approved = sc.budget.approved_amount
            sc.has_budget = True
        except AdminBudget.DoesNotExist:
            approved = Decimal("0")
            sc.has_budget = False
        placed = placed_map.get(sc.id, Decimal("0"))
        sc.available_budget = float(max(Decimal("0"), approved - Decimal(str(placed))))

    context = {
        "po": po,
        "po_items": po_items,
        "totals": totals,
        "buyers": Buyer.objects.all(),
        "seasons": Season.objects.all(),
        "schedules_json": json.dumps(po.delivery_schedules or []),
        "categories": [],
        "all_subcategories": [],
        "vendors": [],
    }
    return render(request, "po_sheet/po_sheet.html", context)


# ---------------------------------------------------------------------------
# Vendor search / select
# ---------------------------------------------------------------------------

@login_required
def search_vendor(request):
    query = (request.GET.get("q") or "").strip()
    vendors = fetch_mssql_vendors(query)
    results = [
        {
            "id": v["vendor_code"],
            "code": v["vendor_code"],
            "name": v["vendor_name"],
            "contact": v["contact_person"],
            "phone": v["phone"],
            "email": v["email"],
            "address": v["address"],
            "city": v["city"],
            "state": v["state"],
            "pin_code": v["pin_code"],
            "gst_number": v["gst_number"],
        }
        for v in vendors
    ]
    return JsonResponse({"vendors": results})


@login_required
@require_POST
def select_vendor(request):
    try:
        data = json.loads(request.body)
        vendor_id = (data.get("vendor_id") or "").strip()
        if not vendor_id:
            return JsonResponse({"success": False, "error": "Vendor is required"})
        vendor = get_or_create_mssql_vendor(vendor_id)
        if not vendor:
            return JsonResponse({"success": False, "error": "Vendor not found"})
        po = PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).first()
        if not po:
            return JsonResponse({"success": False, "error": "Draft PO not found"})
        po.vendor = vendor
        po.save(update_fields=["vendor"])
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("select_vendor error")
        return JsonResponse({"success": False, "error": "Server error"})


@login_required
def vendor_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = Vendor.objects.all()
    if q:
        qs = qs.filter(
            Q(vendor_code__icontains=q)
            | Q(vendor_name__icontains=q)
            | Q(city__icontains=q)
        )
    return render(request, "po_sheet/vendors.html", {"vendors": qs[:100], "q": q})


# ---------------------------------------------------------------------------
# Subcategory search (MSSQL)
# ---------------------------------------------------------------------------

@login_required
def search_subcategory(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    conn = None
    try:
        conn = _get_mssql_conn()
        cursor = conn.cursor()
        if query:
            term = f"%{query}%"
            cursor.execute(
                "SELECT DISTINCT TOP 100 SubCategory, CH4"
                " FROM [dbo].[MCH_View]"
                " WHERE SubCategory IS NOT NULL AND (SubCategory LIKE ? OR CH4 LIKE ?)",
                (term, term),
            )
        else:
            cursor.execute(
                "SELECT DISTINCT TOP 50 SubCategory, CH4"
                " FROM [dbo].[MCH_View] WHERE SubCategory IS NOT NULL"
            )
        rows = cursor.fetchall()
    except Exception:
        logger.exception("MSSQL error in search_subcategory")
        rows = []
    finally:
        if conn:
            conn.close()

    if not rows:
        return JsonResponse({"subcategories": []})

    # One query for all local subcategories in the result set
    names = [r[0] for r in rows]
    local_map = {
        sc.name: sc
        for sc in SubCategory.objects.filter(name__in=names).select_related("budget")
    }
    placed_map = {
        row["subcategory_id"]: row["total"]
        for row in PurchaseOrderItem.objects.filter(purchase_order__is_draft=False)
        .values("subcategory_id")
        .annotate(total=Sum("tot_amt"))
    }

    for subcat_name, ch4 in rows:
        sc = local_map.get(subcat_name)
        has_budget = False
        approved_amount = Decimal("0")
        available_budget = 0.0
        notes = ""
        subcat_id = subcat_name  # fallback when not yet in MySQL

        if sc:
            subcat_id = sc.id
            try:
                approved_amount = sc.budget.approved_amount
                notes = sc.budget.notes or ""
                has_budget = True
            except AdminBudget.DoesNotExist:
                pass
            placed = placed_map.get(sc.id, Decimal("0"))
            available_budget = float(max(Decimal("0"), approved_amount - Decimal(str(placed))))

        results.append({
            "id": subcat_id,
            "name": subcat_name,
            "category": "MSSQL Category",
            "ch4_code": ch4 or "",
            "available_budget": available_budget,
            "has_budget": has_budget,
            "approved_amount": float(approved_amount),
            "notes": notes,
            "unit_price": 0.0,
        })

    return JsonResponse({"subcategories": results})


# ---------------------------------------------------------------------------
# PO item helpers
# ---------------------------------------------------------------------------

def _item_to_dict(item):
    """Serialize a PurchaseOrderItem for JSON responses."""
    return {
        "id": item.id,
        "name": item.subcategory.name,
        # SubCategory has no FK to Category — use ch4_code as the identifier
        "category": item.subcategory.ch4_code or "",
        "ch4_code": item.subcategory.ch4_code or "",
        "order_qty": item.order_qty,
        "tot_qty": item.tot_qty,
        "unit_price": float(item.unit_price),
        "discount_percentage": float(item.discount_percentage),
        "tot_amt": float(item.tot_amt),
        "item_type": item.item_type,
    }


def _po_totals_dict(po, agg):
    return {
        "total_items": po.total_quantity,
        "subtotal": float(agg.get("subtotal") or 0),
        "grand_total": float(po.grand_total),
        "remaining_budget": 0,  # vendor-level budget removed; subcategory-level used instead
    }


# ---------------------------------------------------------------------------
# Add / update / delete PO items
# ---------------------------------------------------------------------------

@login_required
@require_POST
def add_po_item(request):
    try:
        data = json.loads(request.body)
        subcategory_id = data.get("subcategory_id")
        quantity = max(0, int(data.get("quantity", 1)))
        unit_price = Decimal(str(data.get("unit_price") or "0"))
        discount_percentage = Decimal(str(data.get("discount_percentage") or "0"))
        item_type = data.get("item_type", "Fresh")

        po = get_object_or_404(PurchaseOrder, created_by=request.user, is_draft=True)

        try:
            subcategory = SubCategory.objects.get(id=subcategory_id)
        except (SubCategory.DoesNotExist, ValueError, TypeError):
            subcategory, _ = SubCategory.objects.get_or_create(name=str(subcategory_id))

        item, created = PurchaseOrderItem.objects.get_or_create(
            purchase_order=po,
            subcategory=subcategory,
            defaults={
                "unit_price": unit_price,
                "order_qty": quantity,
                "discount_percentage": discount_percentage,
                "item_type": item_type,
            },
        )
        if not created:
            item.order_qty = quantity
            item.discount_percentage = discount_percentage
            item.unit_price = unit_price
            item.item_type = item_type
            item.save()

        _refresh_po_totals(po)

        po_items = po.items.select_related("subcategory").all()
        agg = po_items.aggregate(
            subtotal=Sum(F("tot_qty") * F("unit_price")),
        )
        return JsonResponse({
            "success": True,
            "items": [_item_to_dict(it) for it in po_items],
            "totals": _po_totals_dict(po, agg),
        })
    except (InvalidOperation, ValueError) as e:
        return JsonResponse({"success": False, "error": f"Invalid number: {e}"})
    except Exception:
        logger.exception("add_po_item error")
        return JsonResponse({"success": False, "error": "Server error"})


@login_required
@require_POST
def update_po_item(request, item_id):
    try:
        data = json.loads(request.body)
        item = get_object_or_404(
            PurchaseOrderItem,
            id=item_id,
            purchase_order__created_by=request.user,
            purchase_order__is_draft=True,
        )

        if "quantity" in data:
            item.order_qty = max(0, int(data["quantity"]))
        if "discount_percentage" in data:
            item.discount_percentage = Decimal(str(data["discount_percentage"]))
        if "unit_price" in data:
            item.unit_price = Decimal(str(data["unit_price"]))
        if "item_type" in data:
            item.item_type = data["item_type"]
        item.save()

        po = item.purchase_order
        _refresh_po_totals(po)

        agg = po.items.aggregate(subtotal=Sum(F("tot_qty") * F("unit_price")))
        return JsonResponse({
            "success": True,
            "item": _item_to_dict(item),
            "totals": _po_totals_dict(po, agg),
        })
    except (InvalidOperation, ValueError) as e:
        return JsonResponse({"success": False, "error": f"Invalid number: {e}"})
    except Exception:
        logger.exception("update_po_item error")
        return JsonResponse({"success": False, "error": "Server error"})


@login_required
def delete_po_item(request, item_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "error": "Invalid method"})
    try:
        item = get_object_or_404(
            PurchaseOrderItem,
            id=item_id,
            purchase_order__created_by=request.user,
            purchase_order__is_draft=True,
        )
        po = item.purchase_order
        item.delete()
        _refresh_po_totals(po)

        agg = po.items.aggregate(subtotal=Sum(F("tot_qty") * F("unit_price")))
        return JsonResponse({
            "success": True,
            "totals": _po_totals_dict(po, agg),
        })
    except Exception:
        logger.exception("delete_po_item error")
        return JsonResponse({"success": False, "error": "Server error"})


@login_required
@require_POST
def add_manual_item(request):
    try:
        data = json.loads(request.body)
        item_name = (data.get("item_name") or "").strip()
        unit_price = float(data.get("unit_price", 0))
        quantity = max(0, int(data.get("quantity", 1)))

        if not item_name:
            return JsonResponse({"success": False, "error": "Item name is required"})
        if unit_price <= 0:
            return JsonResponse({"success": False, "error": "Price must be greater than 0"})

        subcategory, _ = SubCategory.objects.get_or_create(name=item_name)

        po = PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).first()
        if not po:
            po = PurchaseOrder.objects.create(
                created_by=request.user,
                is_draft=True,
                po_number=generate_next_po_number(),
            )

        existing = po.items.filter(subcategory=subcategory).first()
        if existing:
            existing.order_qty += quantity
            existing.unit_price = Decimal(str(unit_price))
            existing.save()
        else:
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                subcategory=subcategory,
                order_qty=quantity,
                unit_price=Decimal(str(unit_price)),
            )

        _refresh_po_totals(po)

        po_items = po.items.select_related("subcategory").all()
        agg = po_items.aggregate(subtotal=Sum(F("tot_qty") * F("unit_price")))
        return JsonResponse({
            "success": True,
            "items": [_item_to_dict(it) for it in po_items],
            "totals": _po_totals_dict(po, agg),
        })
    except Exception:
        logger.exception("add_manual_item error")
        return JsonResponse({"success": False, "error": "Server error"})


# ---------------------------------------------------------------------------
# PO field updates
# ---------------------------------------------------------------------------

@login_required
@require_POST
def update_po_fields(request):
    try:
        data = json.loads(request.body)
        po = PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).first()
        if not po:
            return JsonResponse({"success": False, "error": "No draft PO found"})

        update_fields = []
        if "po_type" in data:
            po.po_type = data["po_type"]; update_fields.append("po_type")
        if "season" in data:
            po.season = data["season"]; update_fields.append("season")
        if "agent" in data:
            po.agent = data["agent"]; update_fields.append("agent")
        if "notes" in data:
            po.notes = data["notes"]; update_fields.append("notes")
        # Do NOT allow clients to override po_number freely — it must be system-generated
        if "buyer" in data:
            buyer_id = data["buyer"]
            po.buyer = Buyer.objects.filter(id=buyer_id).first() if buyer_id else None
            update_fields.append("buyer")
        if "vendor" in data:
            vendor_id = data["vendor"]
            po.vendor = get_or_create_mssql_vendor(vendor_id) if vendor_id else None
            update_fields.append("vendor")
        if "po_date" in data and data["po_date"]:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
                try:
                    po.po_date = datetime.strptime(data["po_date"], fmt).date()
                    update_fields.append("po_date")
                    break
                except ValueError:
                    pass

        if update_fields:
            po.save(update_fields=update_fields)
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("update_po_fields error")
        return JsonResponse({"success": False, "error": "Server error"})


# ---------------------------------------------------------------------------
# Save PO (atomic bulk save + submit)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def save_po(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"})

    try:
        with transaction.atomic():
            po = (
                PurchaseOrder.objects
                .select_for_update()
                .filter(created_by=request.user, is_draft=True)
                .first()
            )
            if not po:
                return JsonResponse({"success": False, "error": "No draft PO found"})

            # Ensure a proper sequential number
            if not re.match(r"^PO-\d+$", po.po_number):
                po.po_number = generate_next_po_number()

            # PO header fields
            buyer_id = data.get("buyer")
            po.buyer = Buyer.objects.filter(id=buyer_id).first() if buyer_id else None
            po.agent = data.get("agent", "")
            po.notes = data.get("notes", "")
            po.delivery_schedules = data.get("delivery_schedules", [])
            po.po_type = data.get("po_type", "")
            po.season = data.get("season", "")

            po_date_str = data.get("po_date", "")
            if po_date_str:
                for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
                    try:
                        po.po_date = datetime.strptime(po_date_str, fmt).date()
                        break
                    except ValueError:
                        pass

            items_data = data.get("items", [])

            # --- Budget validation before touching the DB ---
            for item in items_data:
                subcat_id = item.get("subcategory_id")
                if not subcat_id:
                    continue
                try:
                    subcat = SubCategory.objects.select_related("budget").get(id=subcat_id)
                except (SubCategory.DoesNotExist, ValueError, TypeError):
                    continue

                try:
                    budget = subcat.budget
                except AdminBudget.DoesNotExist:
                    continue  # No budget set — allow

                unit_price = Decimal(str(item.get("unit_price", 0)))
                order_qty = int(item.get("order_qty", 0))
                disc = Decimal(str(item.get("discount_percentage", 0)))
                item_amt = unit_price * order_qty * (Decimal("1") - disc / Decimal("100"))

                remaining = get_subcategory_remaining_budget(subcat, exclude_po_id=po.id)
                if item_amt > remaining:
                    over = item_amt - remaining
                    return JsonResponse({
                        "success": False,
                        "error": (
                            f"Budget exceeded for '{subcat.name}': "
                            f"required ₹{item_amt:.2f}, "
                            f"remaining ₹{remaining:.2f} "
                            f"(over by ₹{over:.2f})"
                        ),
                    })

            # --- Replace all items in one shot ---
            # Disconnect signals during bulk-insert so on_commit isn't triggered
            # per item — we'll do one aggregate update at the end instead.
            from django.db.models.signals import post_delete, post_save
            from po_sheet.signals import (
                update_po_totals_on_item_delete,
                update_po_totals_on_item_save,
            )
            post_save.disconnect(update_po_totals_on_item_save, sender=PurchaseOrderItem)
            post_delete.disconnect(update_po_totals_on_item_delete, sender=PurchaseOrderItem)
            try:
                po.items.all().delete()
                new_items = []
                for item in items_data:
                    subcat_id = item.get("subcategory_id")
                    if not subcat_id:
                        continue
                    try:
                        subcat = SubCategory.objects.get(id=subcat_id)
                    except (SubCategory.DoesNotExist, ValueError, TypeError):
                        subcat, _ = SubCategory.objects.get_or_create(name=str(subcat_id))

                    po_item = PurchaseOrderItem(
                        purchase_order=po,
                        subcategory=subcat,
                        unit_price=Decimal(str(item.get("unit_price", 0))),
                        order_qty=int(item.get("order_qty", 0)),
                        discount_percentage=Decimal(str(item.get("discount_percentage", 0))),
                        item_type=item.get("item_type", "Fresh"),
                        size_allocations=item.get("size_allocations", {}),
                    )
                    # Call model's save() so tot_qty/tot_amt are computed
                    po_item.save()
                    new_items.append(po_item)
            finally:
                # Always reconnect — even if an exception occurred
                post_save.connect(update_po_totals_on_item_save, sender=PurchaseOrderItem)
                post_delete.connect(update_po_totals_on_item_delete, sender=PurchaseOrderItem)

            # Mark submitted and persist header
            po.is_draft = False
            po.save()

            # Final aggregate (single query)
            agg = po.items.aggregate(
                total_qty=Sum("tot_qty"),
                grand_total=Sum("tot_amt"),
                subtotal=Sum(F("tot_qty") * F("unit_price")),
            )
            PurchaseOrder.objects.filter(pk=po.pk).update(
                total_quantity=agg["total_qty"] or 0,
                grand_total=agg["grand_total"] or Decimal("0"),
            )

            return JsonResponse({
                "success": True,
                "po_number": po.po_number,
                "totals": {
                    "total_items": agg["total_qty"] or 0,
                    "subtotal": float(agg["subtotal"] or 0),
                    "grand_total": float(agg["grand_total"] or 0),
                },
            })
    except Exception:
        logger.exception("save_po error")
        return JsonResponse({"success": False, "error": "Server error — PO not saved"})


# ---------------------------------------------------------------------------
# Submit PO (lightweight path — just validates & flips is_draft)
# ---------------------------------------------------------------------------

@login_required
def submit_po(request):
    po = get_object_or_404(PurchaseOrder, created_by=request.user, is_draft=True)

    if not po.vendor:
        messages.error(request, "Please select a vendor before submitting")
        return redirect("po_sheet")
    if not po.items.exists():
        messages.error(request, "Please add at least one item before submitting")
        return redirect("po_sheet")

    items = po.items.select_related("subcategory__budget").all()
    for item in items:
        subcat = item.subcategory
        try:
            _ = subcat.budget
        except AdminBudget.DoesNotExist:
            continue
        remaining = get_subcategory_remaining_budget(subcat, exclude_po_id=po.id)
        if item.tot_amt > remaining:
            over = item.tot_amt - remaining
            msg = (
                f"'{subcat.name}': required ₹{item.tot_amt:.2f}, "
                f"remaining ₹{remaining:.2f} (over by ₹{over:.2f})"
            )
            if request.user.is_staff:
                messages.warning(request, f"Budget exceeded — {msg}")
            else:
                messages.error(request, f"Cannot submit — budget exceeded for {msg}")
                return redirect("po_sheet")

    PurchaseOrder.objects.filter(pk=po.pk).update(is_draft=False)
    messages.success(request, f"Purchase Order {po.po_number} submitted successfully")
    return redirect("all_records")


# ---------------------------------------------------------------------------
# New / delete PO
# ---------------------------------------------------------------------------

@login_required
def new_po(request):
    PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).delete()
    PurchaseOrder.objects.create(
        po_number=generate_next_po_number(),
        created_by=request.user,
        is_draft=True,
    )
    messages.success(request, "New purchase order created")
    return redirect("po_sheet")


@login_required
def delete_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if not request.user.is_staff and po.created_by != request.user:
        messages.error(request, "You do not have permission to delete this Purchase Order.")
        return redirect("all_records")
    po_number = po.po_number
    po.delete()
    messages.success(request, f"Purchase Order {po_number} deleted.")
    return redirect("all_records")


# ---------------------------------------------------------------------------
# Preview / print PO
# ---------------------------------------------------------------------------

@login_required
def preview_po(request):
    po_id = request.GET.get("po_id")
    if po_id:
        try:
            po = PurchaseOrder.objects.get(id=po_id)
            # Permission: non-staff can only preview their own POs
            if not request.user.is_staff and po.created_by != request.user:
                return render(request, "po_sheet/print_po.html", {"error": "Permission denied"})
        except (PurchaseOrder.DoesNotExist, ValueError):
            po = None
    else:
        po = (
            PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).first()
            or PurchaseOrder.objects.filter(created_by=request.user).order_by("-updated_at").first()
        )

    if not po:
        return render(request, "po_sheet/print_po.html", {"error": "No PO found"})

    po_items = po.items.select_related("subcategory").all()
    subtotal = sum(item.tot_qty * item.unit_price for item in po_items)
    now = datetime.now()
    return render(request, "po_sheet/print_po.html", {
        "po": po,
        "po_items": po_items,
        "subtotal": subtotal,
        "today": now.strftime("%d/%m/%Y"),
        "print_time": now.strftime("%d/%m/%Y, %I:%M:%S %p"),
    })


# ---------------------------------------------------------------------------
# Send PO (stub — wire up real email/WhatsApp here)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def send_po(request):
    try:
        data = json.loads(request.body)
        email = data.get("email", "")
        whatsapp = data.get("whatsapp", "")
        # TODO: integrate Django email backend or WhatsApp API
        logger.info("send_po stub: email=%s whatsapp=%s", email, whatsapp)
        return JsonResponse({
            "success": True,
            "message": f"PO sent to {email or 'N/A'} / {whatsapp or 'N/A'} (stub)",
        })
    except Exception:
        logger.exception("send_po error")
        return JsonResponse({"success": False, "error": "Server error"})


# ---------------------------------------------------------------------------
# All records
# ---------------------------------------------------------------------------

@login_required
def all_records(request):
    qs = (
        PurchaseOrder.objects
        .select_related("vendor", "created_by", "buyer")
        .prefetch_related("items__subcategory")
        .filter(is_draft=False)
        .order_by("-created_at")
    )
    if not request.user.is_staff:
        qs = qs.filter(created_by=request.user)

    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(
            Q(po_number__icontains=search)
            | Q(vendor__vendor_name__icontains=search)
            | Q(vendor__vendor_code__icontains=search)
            | Q(created_by__username__icontains=search)
        )

    vendor_filter = (request.GET.get("vendor") or "").strip()
    if vendor_filter:
        qs = qs.filter(vendor__vendor_code=vendor_filter)

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    if date_from:
        qs = qs.filter(po_date__gte=date_from)
    if date_to:
        qs = qs.filter(po_date__lte=date_to)

    # Paginate to avoid loading all POs at once
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    vendors_qs = (
        PurchaseOrder.objects.filter(is_draft=False)
        .exclude(vendor__isnull=True)
        .values("vendor__vendor_code", "vendor__vendor_name")
        .distinct()
        .order_by("vendor__vendor_name")
    )

    return render(request, "po_sheet/all_records.html", {
        "records": page_obj.object_list,
        "page_obj": page_obj,
        "search": search,
        "vendor_filter": vendor_filter,
        "date_from": date_from,
        "date_to": date_to,
        "vendors": vendors_qs,
        "total": paginator.count,
        "is_staff": request.user.is_staff,
    })


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@login_required
def export_po_csv(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if not request.user.is_staff and po.created_by != request.user:
        messages.error(request, "You do not have permission to export this Purchase Order.")
        return redirect("all_records")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{po.po_number}_Export.csv"'
    writer = csv.writer(response)

    writer.writerow([
        "PO Number", "PO Date", "PO Type", "Season", "Buyer", "Agent",
        "Vendor Name", "Vendor Code", "Total Quantity", "Grand Total",
        "Status", "Notes", "Delivery Schedules", "Created By", "Created At", "Updated At",
    ])
    writer.writerow([
        po.po_number, po.po_date, po.po_type, po.season,
        po.buyer.name if po.buyer else "",
        po.agent,
        po.vendor.vendor_name if po.vendor else "",
        po.vendor.vendor_code if po.vendor else "",
        po.total_quantity, po.grand_total,
        "Draft" if po.is_draft else "Saved",
        po.notes, po.delivery_schedules,
        po.created_by.username if po.created_by else "",
        po.created_at.strftime("%Y-%m-%d %H:%M:%S") if po.created_at else "",
        po.updated_at.strftime("%Y-%m-%d %H:%M:%S") if po.updated_at else "",
    ])
    writer.writerow([])
    writer.writerow([
        "Item #", "SubCategory", "CH4 Code", "Item Type",
        "Order Qty", "Total Qty", "Unit Price", "Discount %", "Total Amount", "Size Allocations",
    ])
    for i, item in enumerate(po.items.select_related("subcategory").all(), 1):
        sizes = item.size_allocations or {}
        writer.writerow([
            i,
            item.subcategory.name if item.subcategory else "",
            item.subcategory.ch4_code if item.subcategory else "",
            item.item_type,
            item.order_qty, item.tot_qty,
            item.unit_price, item.discount_percentage, item.tot_amt,
            " | ".join(f"{k}:{v}" for k, v in sizes.items()),
        ])
    return response


# ---------------------------------------------------------------------------
# Admin budget
# ---------------------------------------------------------------------------

@login_required
def admin_budget(request):
    if not request.user.is_staff:
        messages.error(request, "Only admin can manage budgets")
        return redirect("po_sheet")

    if request.method == "POST":
        subcategory_id = request.POST.get("subcategory_id", "").strip()
        approved_amount_str = request.POST.get("approved_amount", "").strip()
        notes = request.POST.get("notes", "")

        if subcategory_id and approved_amount_str:
            try:
                approved_amount = Decimal(approved_amount_str)
                if approved_amount < 0:
                    raise ValueError("Amount cannot be negative")

                try:
                    subcat = SubCategory.objects.get(id=int(subcategory_id))
                except (SubCategory.DoesNotExist, ValueError):
                    # Name-based lookup (from MSSQL search)
                    ch4_code = ""
                    conn = None
                    try:
                        conn = _get_mssql_conn()
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT TOP 1 CH4 FROM [dbo].[MCH_View] WHERE SubCategory = ?",
                            (subcategory_id,),
                        )
                        row = cursor.fetchone()
                        if row and row[0]:
                            ch4_code = row[0]
                    except Exception:
                        logger.warning("MSSQL lookup failed in admin_budget for %s", subcategory_id)
                    finally:
                        if conn:
                            conn.close()
                    subcat, _ = SubCategory.objects.get_or_create(
                        name=subcategory_id,
                        defaults={"ch4_code": ch4_code},
                    )

                AdminBudget.objects.update_or_create(
                    subcategory=subcat,
                    defaults={
                        "approved_amount": approved_amount,
                        "approved_by": request.user,
                        "notes": notes,
                    },
                )
                messages.success(
                    request,
                    f"Budget ₹{approved_amount:,.2f} updated for '{subcat.name}'.",
                )
            except Exception as e:
                messages.error(request, f"Error updating budget: {e}")
        return redirect("admin_budget")

    placed_map = {
        row["subcategory_id"]: row["total"]
        for row in PurchaseOrderItem.objects.filter(purchase_order__is_draft=False)
        .values("subcategory_id")
        .annotate(total=Sum("tot_amt"))
    }

    rows = []
    for budget in AdminBudget.objects.select_related("subcategory").order_by("subcategory__name"):
        sc = budget.subcategory
        spent = placed_map.get(sc.id, Decimal("0"))
        rows.append({
            "id": sc.id,
            "name": sc.name,
            "ch4_code": sc.ch4_code or "—",
            "approved_amount": budget.approved_amount,
            "spent_amount": spent,
            "balance_amount": budget.approved_amount - spent,
            "notes": budget.notes or "",
        })

    paginator = Paginator(rows, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "po_sheet/admin_budget.html", {
        "subcategories": page_obj.object_list,
        "page_obj": page_obj,
        "total_budgeted_count": paginator.count,
    })


# ---------------------------------------------------------------------------
# Size manager
# ---------------------------------------------------------------------------

@login_required
def size_manager(request):
    return render(request, "po_sheet/size_manager.html", {"all_subcategories": []})


@login_required
def get_subcategory_sizes(request, subcategory_id):
    try:
        sc = SubCategory.objects.get(id=subcategory_id)
    except (SubCategory.DoesNotExist, ValueError):
        sc = SubCategory.objects.filter(name=subcategory_id).first()
    if not sc:
        return JsonResponse({"success": True, "sizes": []})
    sizes = list(SubCategorySize.objects.filter(subcategory=sc).order_by("id").values("id", "name"))
    return JsonResponse({"success": True, "sizes": sizes})


@login_required
@require_POST
def add_subcategory_sizes(request):
    try:
        data = json.loads(request.body)
        subcat_id = data.get("subcategory_id")
        size_names = data.get("sizes", [])

        try:
            sc = SubCategory.objects.get(id=subcat_id)
        except (SubCategory.DoesNotExist, ValueError, TypeError):
            sc, _ = SubCategory.objects.get_or_create(name=str(subcat_id))

        for name in size_names:
            name = name.strip()
            if name:
                SubCategorySize.objects.get_or_create(subcategory=sc, name=name)

        sizes = list(SubCategorySize.objects.filter(subcategory=sc).order_by("id").values("id", "name"))
        return JsonResponse({"success": True, "sizes": sizes})
    except Exception:
        logger.exception("add_subcategory_sizes error")
        return JsonResponse({"success": False, "error": "Server error"})


@login_required
@require_POST
def remove_subcategory_size(request):
    try:
        data = json.loads(request.body)
        subcat_id = data.get("subcategory_id")
        size_id = data.get("size_id")

        try:
            sc = SubCategory.objects.get(id=subcat_id)
        except (SubCategory.DoesNotExist, ValueError, TypeError):
            sc = SubCategory.objects.filter(name=str(subcat_id)).first()
        if not sc:
            return JsonResponse({"success": False, "error": "Subcategory not found"})

        get_object_or_404(SubCategorySize, id=size_id, subcategory=sc).delete()
        sizes = list(SubCategorySize.objects.filter(subcategory=sc).order_by("id").values("id", "name"))
        return JsonResponse({"success": True, "sizes": sizes})
    except Exception:
        logger.exception("remove_subcategory_size error")
        return JsonResponse({"success": False, "error": "Server error"})


# ---------------------------------------------------------------------------
# User management (staff only)
# ---------------------------------------------------------------------------

@login_required
def manage_users(request):
    if not request.user.is_staff:
        messages.error(request, "Only administrators can manage users")
        return redirect("po_sheet")

    if request.method == "POST":
        action = request.POST.get("action")
        username = request.POST.get("username", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        is_staff = request.POST.get("role") == "admin"
        is_active = "is_active" in request.POST

        if action == "create":
            if not username or not password:
                messages.error(request, "Username and Password are required")
            elif User.objects.filter(username=username).exists():
                messages.error(request, f"User '{username}' already exists")
            else:
                try:
                    User.objects.create_user(
                        username=username, password=password, email=email,
                        first_name=first_name, last_name=last_name,
                        is_staff=is_staff, is_active=is_active,
                    )
                    messages.success(request, f"User '{username}' created")
                except Exception as e:
                    messages.error(request, f"Error: {e}")
            return redirect("manage_users")

        if action == "edit":
            user_to_edit = get_object_or_404(User, id=request.POST.get("user_id"))
            if username and username != user_to_edit.username:
                if User.objects.filter(username=username).exclude(id=user_to_edit.id).exists():
                    messages.error(request, f"Username '{username}' already taken")
                    return redirect("manage_users")
                user_to_edit.username = username
            user_to_edit.first_name = first_name
            user_to_edit.last_name = last_name
            user_to_edit.email = email
            user_to_edit.is_staff = is_staff
            user_to_edit.is_active = is_active
            if password:
                user_to_edit.set_password(password)
            try:
                user_to_edit.save()
                messages.success(request, f"User '{user_to_edit.username}' updated")
            except Exception as e:
                messages.error(request, f"Error: {e}")
            return redirect("manage_users")

    users = User.objects.all().order_by("-date_joined")
    return render(request, "po_sheet/manage_users.html", {"users": users})


@login_required
def delete_user(request, user_id):
    if not request.user.is_staff:
        messages.error(request, "Only administrators can manage users")
        return redirect("po_sheet")
    user_to_delete = get_object_or_404(User, id=user_id)
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own account")
    else:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"User '{username}' deleted")
    return redirect("manage_users")

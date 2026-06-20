from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Q, Sum, F
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
import json
from datetime import datetime
from decimal import Decimal
from .models import Vendor, SubCategory, PurchaseOrder, PurchaseOrderItem, AdminBudget, Buyer, SubCategorySize, Season
from .forms import AdminBudgetForm


def get_mssql_connection():
    """Dynamically build ODBC connection from settings.py database configuration"""
    from django.conf import settings
    import pyodbc
    db = settings.DATABASES['mssql']
    driver = db.get('OPTIONS', {}).get('driver', 'ODBC Driver 17 for SQL Server')
    server = db.get('HOST', 'localhost')
    port = db.get('PORT', '')
    database = db.get('NAME', '')
    user = db.get('USER', '')
    password = db.get('PASSWORD', '')
    
    server_str = f"{server},{port}" if port else server
    conn_str = f"DRIVER={{{driver}}};SERVER={server_str};DATABASE={database};UID={user};PWD={password}"
    return pyodbc.connect(conn_str)


def fetch_mssql_vendors(query=None):
    vendors_list = []
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        if query:
            sql = """
                SELECT lifnr, name, city, gstNo, postCode, street, email1 
                FROM [dbo].[Vendor_B]
                WHERE lifnr LIKE ? OR name LIKE ? OR city LIKE ?
            """
            like_val = f"%{query}%"
            cursor.execute(sql, (like_val, like_val, like_val))
        else:
            cursor.execute("SELECT lifnr, name, city, gstNo, postCode, street, email1 FROM [dbo].[Vendor_B]")
        
        for row in cursor.fetchall():
            lifnr = row[0]
            name = row[1] if row[1] else ''
            city = row[2] if row[2] else ''
            gst_no = row[3] if row[3] else ''
            post_code = str(row[4]) if row[4] is not None else ''
            street = row[5] if row[5] else ''
            email1 = row[6] if row[6] else ''
            
            vendors_list.append({
                'vendor_code': lifnr,
                'vendor_name': name,
                'address': street,
                'city': city,
                'state': '',
                'pin_code': post_code,
                'email': email1,
                'phone': '',
                'gst_number': gst_no,
                'contact_person': '',
            })
        cursor.close()
        conn.close()
    except Exception as e:
        print("MSSQL Error in fetch_mssql_vendors:", e)
    return vendors_list


def get_or_create_mssql_vendor(vendor_code):
    if not vendor_code:
        return None
    vendor_code = str(vendor_code).strip()
    
    local_vendor = Vendor.objects.filter(vendor_code=vendor_code).first()
    if local_vendor:
        return local_vendor
        
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, city, gstNo, postCode, street, email1 
            FROM [dbo].[Vendor_B] 
            WHERE lifnr = ?
        """, (vendor_code,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row:
            name = row[0] if row[0] else ''
            city = row[1] if row[1] else ''
            gst_no = row[2] if row[2] else ''
            post_code = str(row[3]) if row[3] is not None else ''
            street = row[4] if row[4] else ''
            email1 = row[5] if row[5] else ''
            
            vendor = Vendor.objects.create(
                vendor_code=vendor_code,
                vendor_name=name,
                address=street,
                city=city,
                state='',
                pin_code=post_code,
                email=email1,
                phone='',
                gst_number=gst_no,
                contact_person='',
            )
            return vendor
    except Exception as e:
        print(f"MSSQL Error in get_or_create_mssql_vendor for {vendor_code}:", e)
        
    vendor, _ = Vendor.objects.get_or_create(
        vendor_code=vendor_code,
        defaults={
            'vendor_name': vendor_code,
            'address': '',
            'city': '',
            'state': '',
            'pin_code': '',
            'email': '',
            'phone': '',
            'gst_number': '',
            'contact_person': '',
        }
    )
    return vendor



def get_subcategory_remaining_budget(subcategory, exclude_po_id=None, include_draft_po_id=None):
    """Calculate remaining budget at subcategory level - includes draft and submitted/approved POs"""
    if not subcategory:
        return Decimal('0')
    
    try:
        budget = subcategory.budget
    except Exception:
        return Decimal('0')
    
    if not budget:
        return Decimal('0')
    
    # Count SAVED POs
    query = PurchaseOrderItem.objects.filter(
        subcategory=subcategory,
        purchase_order__is_draft=False
    )
    if exclude_po_id:
        query = query.exclude(purchase_order_id=exclude_po_id)
        
    subcat_total = query.aggregate(total=Sum('tot_amt'))['total'] or Decimal('0')
    
    # If a draft PO is provided, add its tot_amt to the calculation
    if include_draft_po_id:
        draft_item = PurchaseOrderItem.objects.filter(
            purchase_order_id=include_draft_po_id,
            purchase_order__is_draft=True,
            subcategory=subcategory
        ).aggregate(total=Sum('tot_amt'))['total'] or Decimal('0')
        subcat_total += draft_item
        
    remaining = budget.approved_amount - subcat_total
    return remaining


def get_vendor_remaining_budget(vendor, exclude_po_id=None, include_draft_po_id=None):
    """Backward compatibility helper"""
    return Decimal('0')


def get_current_user(request):
    """Helper to get user or fallback to admin for demo purposes"""
    if request.user.is_authenticated:
        return request.user
    from django.contrib.auth.models import User
    try:
        return User.objects.get(username='admin')
    except User.DoesNotExist:
        return None


def generate_next_po_number():
    import re
    # Retrieve only the 100 most recent POs to find the max number, which is extremely fast
    pos = PurchaseOrder.objects.order_by('-id')[:100].values_list('po_number', flat=True)
    max_num = 0
    for po_num in pos:
        match = re.search(r'(?:PO-|DRAFT-)?(\d+)', po_num)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    
    # If no sequential PO was found in the last 100 records, fallback to scanning all but only values_list
    if max_num == 0:
        pos = PurchaseOrder.objects.values_list('po_number', flat=True)
        for po_num in pos:
            match = re.search(r'(?:PO-|DRAFT-)?(\d+)', po_num)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    next_num = max_num + 1
    return f"PO-{next_num:04d}"


@login_required
@ensure_csrf_cookie
def po_sheet(request):
    """Main Purchase Order sheet interface"""
    user = get_current_user(request)
    if not user:
        return redirect('login')
        
    po = PurchaseOrder.objects.filter(created_by=user, is_draft=True).first()
    created = False
    if not po:
        po = PurchaseOrder.objects.create(
            created_by=user,
            is_draft=True,
            po_number=generate_next_po_number(),
            total_quantity=0,
            grand_total=0,
        )
        created = True
    
    import re
    if not created and not re.match(r'^PO-\d{4}$', po.po_number):
        po.po_number = generate_next_po_number()
        po.save(update_fields=['po_number'])
    
    po_items = po.items.select_related('subcategory').all()
    
    # Calculate PO totals
    totals = {}
    if po_items.exists():
        aggregate = po_items.aggregate(
            total_qty=Sum('tot_qty'),
            subtotal=Sum(F('tot_qty') * F('unit_price')),
            grand_total=Sum('tot_amt')
        )
        totals = {
            'items': aggregate['total_qty'] or 0,
            'subtotal': aggregate['subtotal'] or Decimal('0'),
            'grand_total': aggregate['grand_total'] or Decimal('0'),
        }
    else:
        totals = {
            'items': 0,
            'subtotal': Decimal('0'),
            'grand_total': Decimal('0'),
        }
    
    # Update PO totals in DB
    po.total_quantity = totals['items']
    po.grand_total = totals['grand_total']
    po.save(update_fields=['total_quantity', 'grand_total'])
    
    # Calculate budgets for existing local subcategories
    placed_qtys = PurchaseOrderItem.objects.filter(
        purchase_order__is_draft=False
    ).values('subcategory_id').annotate(total=Sum('tot_amt'))
    placed_qty_map = {item['subcategory_id']: item['total'] for item in placed_qtys}

    for item in po_items:
        sc = item.subcategory
        if sc:
            has_budget = False
            try:
                approved_amount = sc.budget.approved_amount
                has_budget = True
            except Exception:
                approved_amount = Decimal('0')
            placed_qty = placed_qty_map.get(sc.id, 0)
            sc.available_budget = float(max(Decimal('0'), approved_amount - Decimal(str(placed_qty))))
            sc.has_budget = has_budget

    categories = []
    all_subcategories = []
    budget = None
    remaining_budget = Decimal('0')
    buyers = Buyer.objects.all()
    vendors = []
    schedules_json = json.dumps(po.delivery_schedules or [])
    
    context = {
        'po': po,
        'po_items': po_items,
        'categories': categories,
        'all_subcategories': all_subcategories,
        'budget': budget,
        'totals': totals,
        'remaining_budget': remaining_budget,
        'buyers': buyers,
        'vendors': vendors,
        'seasons': Season.objects.all(),
        'schedules_json': schedules_json,
    }
    return render(request, 'po_sheet/po_sheet.html', context)


@csrf_exempt
@login_required
def search_vendor(request):
    query = (request.GET.get('q') or '').strip()
    vendors = fetch_mssql_vendors(query)[:100]

    results = []
    for v in vendors:
        results.append({
            'id': v['vendor_code'],
            'code': v['vendor_code'],
            'name': v['vendor_name'],
            'contact': v['contact_person'] or '',
            'phone': v['phone'] or '',
            'email': v['email'] or '',
            'address': v['address'] or '',
            'city': v['city'] or '',
            'state': v['state'] or '',
            'pin_code': v['pin_code'] or '',
            'gst_number': v['gst_number'] or '',
        })

    return JsonResponse({'vendors': results})


@csrf_exempt
@login_required
def select_vendor(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})
    try:
        data = json.loads(request.body)
        vendor_id = data.get('vendor_id')
        if not vendor_id:
            return JsonResponse({'success': False, 'error': 'Vendor is required'})

        vendor = get_or_create_mssql_vendor(vendor_id)
        if not vendor:
            return JsonResponse({'success': False, 'error': 'Vendor not found'})

        user = get_current_user(request)
        po = PurchaseOrder.objects.filter(created_by=user, is_draft=True).first()
        if not po:
            return JsonResponse({'success': False, 'error': 'Draft PO not found'})

        po.vendor = vendor
        po.save(update_fields=['vendor'])
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt
@login_required
def vendor_list(request):
    q = (request.GET.get("q") or "").strip()
    vendors = Vendor.objects.all()

    if q:
        vendors = vendors.filter(
            Q(vendor_code__icontains=q) |
            Q(vendor_name__icontains=q) |
            Q(city__icontains=q)
        )

    vendors = vendors[:100]
    return render(request, "po_sheet/vendors.html", {"vendors": vendors, "q": q})


@csrf_exempt
@login_required
def search_subcategory(request):
    query = request.GET.get('q', '').strip()
    
    results = []
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        
        if query:
            search_term = f"%{query}%"
            cursor.execute(
                "SELECT DISTINCT SubCategory, CH4 FROM [dbo].[MCH_View] WHERE SubCategory IS NOT NULL AND (SubCategory LIKE ? OR CH4 LIKE ?)", 
                (search_term, search_term)
            )
        else:
            cursor.execute("SELECT DISTINCT TOP 50 SubCategory, CH4 FROM [dbo].[MCH_View] WHERE SubCategory IS NOT NULL")
            
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Get placed amounts per subcategory
        placed_amts = PurchaseOrderItem.objects.filter(
            purchase_order__is_draft=False
        ).values('subcategory_id').annotate(total=Sum('tot_amt'))
        placed_qty_map = {item['subcategory_id']: item['total'] for item in placed_amts}

        # Pre-fetch all local subcategories once to avoid N+1 query in the loop
        local_subcat_names = [row[0] for row in rows]
        local_subcats = {
            sc.name: sc
            for sc in SubCategory.objects.filter(name__in=local_subcat_names).select_related('budget')
        }

        for row in rows:
            subcat_name = row[0]
            ch4 = row[1] if row[1] else ''
            
            has_budget = False
            available_budget = 0.0
            approved_amount = Decimal('0')
            notes = ''
            if subcat_name in local_subcats:
                sc = local_subcats[subcat_name]
                subcat_id = sc.id
                category_name = 'MSSQL Category'
                if hasattr(sc, 'budget') and sc.budget:
                    approved_amount = sc.budget.approved_amount
                    notes = sc.budget.notes or ''
                    has_budget = True
                else:
                    approved_amount = Decimal('0')
                placed_qty = placed_qty_map.get(sc.id, Decimal('0'))
                available_budget = float(max(Decimal('0'), approved_amount - placed_qty))
            else:
                subcat_id = subcat_name
                category_name = 'MSSQL Category'

            results.append({
                'id': subcat_id,
                'name': subcat_name,
                'category': category_name,
                'ch4_code': ch4,
                'available_budget': available_budget,
                'has_budget': has_budget,
                'approved_amount': float(approved_amount),
                'notes': notes,
                'unit_price': 0.0,
            })
            
    except Exception as e:
        print("MSSQL Error:", e)

    return JsonResponse({'subcategories': results})


@csrf_exempt
@login_required
def add_po_item(request):
    """Add item to purchase order"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            subcategory_id = data.get('subcategory_id')
            quantity = int(data.get('quantity', 1))
            unit_price = data.get('unit_price')
            discount_percentage = Decimal(str(data.get('discount_percentage', 0)))
            item_type = data.get('item_type', 'Fresh')
            
            user = get_current_user(request)
            po = get_object_or_404(PurchaseOrder, created_by=user, is_draft=True)
            
            try:
                subcategory = SubCategory.objects.get(id=subcategory_id)
            except (SubCategory.DoesNotExist, ValueError):
                subcategory, _ = SubCategory.objects.get_or_create(
                    name=subcategory_id,
                )
            price = Decimal(str(unit_price)) if unit_price is not None else Decimal('0.00')

            item, created = PurchaseOrderItem.objects.get_or_create(
                purchase_order=po,
                subcategory=subcategory,
                defaults={
                    'unit_price': price,
                    'order_qty': quantity,
                    'discount_percentage': discount_percentage,
                    'item_type': item_type,
                }
            )
            if not created:
                item.order_qty = quantity
                item.discount_percentage = discount_percentage
                if unit_price is not None:
                    item.unit_price = price
                item.item_type = item_type
                item.save()

            # Recalculate PO totals
            po_items = po.items.all()
            aggregate = po_items.aggregate(
                total_qty=Sum('tot_qty'),
                subtotal=Sum(F('tot_qty') * F('unit_price')),
                grand_total=Sum('tot_amt')
            )
            po.total_quantity = aggregate['total_qty'] or 0
            po.grand_total = aggregate['grand_total'] or Decimal('0')
            po.save(update_fields=['total_quantity', 'grand_total'])
            
            remaining_budget = get_vendor_remaining_budget(po.vendor, exclude_po_id=po.id, include_draft_po_id=po.id) if po.vendor else Decimal('0')

            updated_items = []
            for it in po_items:
                updated_items.append({
                    'id': it.id,
                    'name': it.subcategory.name,
                    'category': it.subcategory.category.name if it.subcategory.category else '',
                    'ch4_code': it.subcategory.ch4_code or '',
                    'order_qty': it.order_qty,
                    'tot_qty': it.tot_qty,
                    'unit_price': float(it.unit_price),
                    'discount_percentage': float(it.discount_percentage),
                    'tot_amt': float(it.tot_amt),
                    'item_type': it.item_type,
                })

            return JsonResponse({
                'success': True,
                'items': updated_items,
                'totals': {
                    'total_items': po.total_quantity,
                    'subtotal': float(aggregate['subtotal'] or 0),
                    'grand_total': float(po.grand_total),
                    'remaining_budget': float(remaining_budget)
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@csrf_exempt
@login_required
def update_po_item(request, item_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            item = get_object_or_404(PurchaseOrderItem, id=item_id, purchase_order__created_by=request.user)
            
            if 'quantity' in data:
                item.order_qty = int(data['quantity'])
            if 'discount_percentage' in data:
                item.discount_percentage = Decimal(str(data['discount_percentage']))
            if 'unit_price' in data:
                item.unit_price = Decimal(str(data['unit_price']))
            if 'item_type' in data:
                item.item_type = data['item_type']
            
            item.save()

            po = item.purchase_order
            po_items = po.items.all()
            aggregate = po_items.aggregate(
                total_qty=Sum('tot_qty'),
                subtotal=Sum(F('tot_qty') * F('unit_price')),
                grand_total=Sum('tot_amt')
            )
            po.total_quantity = aggregate['total_qty'] or 0
            po.grand_total = aggregate['grand_total'] or Decimal('0')
            po.save(update_fields=['total_quantity', 'grand_total'])

            remaining_budget = get_vendor_remaining_budget(po.vendor, exclude_po_id=po.id, include_draft_po_id=po.id) if po.vendor else Decimal('0')

            return JsonResponse({
                'success': True,
                'item': {
                    'id': item.id,
                    'order_qty': item.order_qty,
                    'tot_qty': item.tot_qty,
                    'unit_price': float(item.unit_price),
                    'discount_percentage': float(item.discount_percentage),
                    'tot_amt': float(item.tot_amt),
                    'item_type': item.item_type,
                },
                'totals': {
                    'total_items': po.total_quantity,
                    'subtotal': float(aggregate['subtotal'] or 0),
                    'grand_total': float(po.grand_total),
                    'remaining_budget': float(remaining_budget)
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@csrf_exempt
@login_required
def delete_po_item(request, item_id):
    if request.method == 'DELETE':
        try:
            item = get_object_or_404(PurchaseOrderItem, id=item_id, purchase_order__created_by=request.user)
            po = item.purchase_order
            item.delete()

            po_items = po.items.all()
            aggregate = po_items.aggregate(
                total_qty=Sum('tot_qty'),
                subtotal=Sum(F('tot_qty') * F('unit_price')),
                grand_total=Sum('tot_amt')
            )
            po.total_quantity = aggregate['total_qty'] or 0
            po.grand_total = aggregate['grand_total'] or Decimal('0')
            po.save(update_fields=['total_quantity', 'grand_total'])

            remaining_budget = get_vendor_remaining_budget(po.vendor, exclude_po_id=po.id, include_draft_po_id=po.id) if po.vendor else Decimal('0')

            return JsonResponse({
                'success': True,
                'totals': {
                    'total_items': po.total_quantity,
                    'subtotal': float(aggregate['subtotal'] or 0),
                    'grand_total': float(po.grand_total),
                    'remaining_budget': float(remaining_budget)
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@csrf_exempt
@login_required
def add_manual_item(request):
    """Add manually entered item"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            category_name = data.get('category', 'Manual')
            item_name = data.get('item_name')
            unit_price = float(data.get('unit_price', 0))
            quantity = int(data.get('quantity', 1))
            
            if not item_name:
                return JsonResponse({'success': False, 'error': 'Item name is required'})
            if unit_price <= 0:
                return JsonResponse({'success': False, 'error': 'Price must be greater than 0'})
            
            subcategory, _ = SubCategory.objects.get_or_create(
                name=item_name,
            )
            
            po = PurchaseOrder.objects.filter(created_by=request.user, is_draft=True).first()
            if not po:
                po = PurchaseOrder.objects.create(
                    created_by=request.user,
                    is_draft=True,
                    po_number=generate_next_po_number(),
                    total_quantity=0,
                    grand_total=0,
                )
            
            existing_item = po.items.filter(subcategory=subcategory).first()
            if existing_item:
                existing_item.order_qty += quantity
                existing_item.unit_price = Decimal(str(unit_price))
                existing_item.save()
            else:
                PurchaseOrderItem.objects.create(
                    purchase_order=po,
                    subcategory=subcategory,
                    order_qty=quantity,
                    unit_price=Decimal(str(unit_price))
                )
            
            po_items = po.items.all()
            aggregate = po_items.aggregate(
                total_qty=Sum('tot_qty'),
                subtotal=Sum(F('tot_qty') * F('unit_price')),
                grand_total=Sum('tot_amt')
            )
            po.total_quantity = aggregate['total_qty'] or 0
            po.grand_total = aggregate['grand_total'] or Decimal('0')
            po.save(update_fields=['total_quantity', 'grand_total'])
            
            remaining_budget = get_vendor_remaining_budget(po.vendor, exclude_po_id=po.id, include_draft_po_id=po.id) if po.vendor else Decimal('0')

            updated_items = []
            for it in po.items.all():
                updated_items.append({
                    'id': it.id,
                    'name': it.subcategory.name,
                    'category': it.subcategory.category.name if it.subcategory.category else '',
                    'ch4_code': it.subcategory.ch4_code or '',
                    'order_qty': it.order_qty,
                    'tot_qty': it.tot_qty,
                    'unit_price': float(it.unit_price),
                    'discount_percentage': float(it.discount_percentage),
                    'tot_amt': float(it.tot_amt),
                    'item_type': it.item_type,
                })

            return JsonResponse({
                'success': True,
                'items': updated_items,
                'totals': {
                    'total_items': po.total_quantity,
                    'subtotal': float(aggregate['subtotal'] or 0),
                    'grand_total': float(po.grand_total),
                    'remaining_budget': float(remaining_budget)
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def admin_budget(request):
    if not request.user.is_staff:
        messages.error(request, 'Only admin can manage budgets')
        return redirect('po_sheet')

    if request.method == 'POST':
        subcategory_id = request.POST.get('subcategory_id')
        approved_amount = request.POST.get('approved_amount')
        notes = request.POST.get('notes', '')
        
        if subcategory_id and approved_amount:
            try:
                try:
                    subcat = SubCategory.objects.get(id=subcategory_id)
                except (SubCategory.DoesNotExist, ValueError):
                    # subcategory_id is name of mssql subcategory. Fetch it, find or create.
                    ch4_code = ''
                    try:
                        conn = get_mssql_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT TOP 1 CH4 FROM [dbo].[MCH_View] WHERE SubCategory = ?", (subcategory_id,))
                        row = cursor.fetchone()
                        if row and row[0]:
                            ch4_code = row[0]
                        cursor.close()
                        conn.close()
                    except Exception:
                        pass
                    
                    subcat, _ = SubCategory.objects.get_or_create(
                        name=subcategory_id,
                        defaults={
                            'ch4_code': ch4_code
                        }
                    )
                
                AdminBudget.objects.update_or_create(
                    subcategory=subcat,
                    defaults={
                        'approved_amount': Decimal(approved_amount),
                        'approved_by': request.user,
                        'notes': notes
                    }
                )
                messages.success(request, f"Budget of ₹{approved_amount} successfully updated for '{subcat.name}'.")
            except Exception as e:
                messages.error(request, f"Error updating budget: {str(e)}")
        return redirect('admin_budget')

    # Get placed amounts per subcategory
    placed_amts = PurchaseOrderItem.objects.filter(
        purchase_order__is_draft=False
    ).values('subcategory_id').annotate(total=Sum('tot_amt'))
    placed_amt_map = {item['subcategory_id']: item['total'] for item in placed_amts}

    # Fetch all local budgets
    local_budgets = AdminBudget.objects.select_related('subcategory').all()

    table_subcategories = []
    for budget in local_budgets:
        sc = budget.subcategory
        approved_amt = budget.approved_amount
        spent_amt = placed_amt_map.get(sc.id, Decimal('0'))
        balance_amt = approved_amt - spent_amt
        
        table_subcategories.append({
            'id': sc.id,
            'category_name': "MSSQL Category",
            'name': sc.name,
            'ch4_code': sc.ch4_code or '—',
            'approved_amount': approved_amt,
            'spent_amount': spent_amt,
            'balance_amount': balance_amt,
            'notes': budget.notes or ''
        })

    # Sort subcategories alphabetically by name
    table_subcategories.sort(key=lambda x: x['name'])

    # Django Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(table_subcategories, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'po_sheet/admin_budget.html', {
        'subcategories': page_obj.object_list,
        'page_obj': page_obj,
        'total_budgeted_count': len(table_subcategories)
    })


@login_required
def submit_po(request):
    po = get_object_or_404(PurchaseOrder, created_by=request.user, is_draft=True)
    
    if not po.vendor:
        messages.error(request, 'Please select a vendor before submitting')
        return redirect('po_sheet')
    if po.items.count() == 0:
        messages.error(request, 'Please add at least one item before submitting')
        return redirect('po_sheet')
    
    for item in po.items.all():
        subcat = item.subcategory
        rem_subcat_budget = get_subcategory_remaining_budget(subcat, exclude_po_id=po.id)
        try:
            budget = subcat.budget
            if item.tot_amt > rem_subcat_budget:
                msg = f"Subcategory '{subcat.name}' budget exceeded by ₹{item.tot_amt - rem_subcat_budget:.2f} (Remaining: ₹{rem_subcat_budget:.2f}, Required: ₹{item.tot_amt:.2f})."
                messages.warning(request, msg)
                if not request.user.is_staff:
                    messages.error(request, f"Cannot submit PO as subcategory '{subcat.name}' budget is exceeded.")
                    return redirect('po_sheet')
        except Exception:
            pass
    
    po.is_draft = False
    po.save()
    messages.success(request, f'Purchase Order {po.po_number} saved successfully')
    return redirect('all_records')


@login_required
def new_po(request):
    user = get_current_user(request)
    if not user:
        return redirect('login')

    # Delete current draft
    PurchaseOrder.objects.filter(
        created_by=user,
        is_draft=True
    ).delete()
    
    # Create new draft
    po = PurchaseOrder.objects.create(
        po_number=generate_next_po_number(),
        created_by=user,
        is_draft=True
    )
    
    messages.success(request, 'New purchase order created')
    return redirect('po_sheet')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('po_sheet')
        else:
            messages.error(request, 'Invalid username or password')
    return render(request, 'po_sheet/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@csrf_exempt
@login_required
def update_po_fields(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user = get_current_user(request)
            po = PurchaseOrder.objects.filter(created_by=user, is_draft=True).first()
            if po:
                if 'po_type' in data: po.po_type = data['po_type']
                if 'season' in data: po.season = data['season']
                if 'agent' in data: po.agent = data['agent']
                if 'notes' in data: po.notes = data['notes']
                if 'po_number' in data: po.po_number = data['po_number']
                if 'buyer' in data:
                    buyer_id = data['buyer']
                    po.buyer = Buyer.objects.filter(id=buyer_id).first() if buyer_id else None
                if 'vendor' in data:
                    vendor_id = data['vendor']
                    po.vendor = get_or_create_mssql_vendor(vendor_id) if vendor_id else None
                if 'po_date' in data:
                    try:
                        po.po_date = datetime.strptime(data['po_date'], '%Y-%m-%d').date()
                    except:
                        pass
                po.save()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@csrf_exempt
@login_required
def save_po(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    from django.db import transaction
    from django.db.models.signals import post_save, post_delete
    from po_sheet.signals import update_po_totals_on_item_save, update_po_totals_on_item_delete

    try:
        data = json.loads(request.body)
        user = get_current_user(request)
        
        with transaction.atomic():
            po = PurchaseOrder.objects.select_for_update().filter(created_by=user, is_draft=True).first()
            if not po:
                return JsonResponse({'success': False, 'error': 'No draft PO found'})
            
            # If PO is draft, assign sequential PO number series
            if po.po_number.startswith('DRAFT'):
                po.po_number = generate_next_po_number()
                
            # Save PO fields
            buyer_id = data.get('buyer')
            if buyer_id:
                po.buyer = Buyer.objects.filter(id=buyer_id).first()
            else:
                po.buyer = None

            po.agent = data.get('agent', '')
            po.notes = data.get('notes', '')
            po.delivery_schedules = data.get('delivery_schedules', [])
            po.po_type = data.get('po_type', '')
            po.season = data.get('season', '')
            
            po_date_str = data.get('po_date')
            if po_date_str:
                try:
                    po.po_date = datetime.strptime(po_date_str, '%Y-%m-%d').date()
                except:
                    try:
                        po.po_date = datetime.strptime(po_date_str, '%d.%m.%Y').date()
                    except:
                        pass
            
            items_data = data.get('items', [])
            
            # Validate budget limits before deleting or saving
            for item in items_data:
                subcat_id = item.get('subcategory_id')
                if not subcat_id:
                    continue
                try:
                    subcat = SubCategory.objects.get(id=subcat_id)
                except (SubCategory.DoesNotExist, ValueError):
                    continue
                
                unit_price = Decimal(str(item.get('unit_price', 0)))
                order_qty = int(item.get('order_qty', 0))
                tot_qty = order_qty
                discount_percentage = Decimal(str(item.get('discount_percentage', 0)))
                discount_factor = Decimal('1') - (discount_percentage / Decimal('100'))
                item_tot_amt = unit_price * tot_qty * discount_factor
                
                # Get remaining budget (excluding this PO's current items)
                rem_budget = get_subcategory_remaining_budget(subcat, exclude_po_id=po.id)
                
                try:
                    budget = subcat.budget
                    if item_tot_amt > rem_budget:
                        return JsonResponse({
                            'success': False,
                            'error': 'you reached the limit amount'
                        })
                except Exception:
                    pass
            
            # Disconnect signals to avoid redundant database recalculation during loop
            post_save.disconnect(update_po_totals_on_item_save, sender=PurchaseOrderItem)
            post_delete.disconnect(update_po_totals_on_item_delete, sender=PurchaseOrderItem)
            
            try:
                po.items.all().delete()
                
                for item in items_data:
                    subcat_id = item.get('subcategory_id')
                    if not subcat_id:
                        continue
                    
                    try:
                        subcat = SubCategory.objects.get(id=subcat_id)
                    except (SubCategory.DoesNotExist, ValueError):
                        subcat, _ = SubCategory.objects.get_or_create(
                            name=subcat_id,
                        )
                    
                    unit_price = Decimal(str(item.get('unit_price', 0)))
                    order_qty = int(item.get('order_qty', 0))
                    discount_percentage = Decimal(str(item.get('discount_percentage', 0)))
                    item_type = item.get('item_type', 'Fresh')
                    
                    size_allocations = item.get('size_allocations', {})
                    
                    po_item = PurchaseOrderItem(
                        purchase_order=po,
                        subcategory=subcat,
                        unit_price=unit_price,
                        order_qty=order_qty,
                        discount_percentage=discount_percentage,
                        item_type=item_type,
                        size_allocations=size_allocations
                    )
                    po_item.save()
            finally:
                # Always reconnect signals
                post_save.connect(update_po_totals_on_item_save, sender=PurchaseOrderItem)
                post_delete.connect(update_po_totals_on_item_delete, sender=PurchaseOrderItem)
                    
            po.is_draft = False
            po.save()
            
            # Recalculate totals once at the end
            po_items = po.items.all()
            aggregate = po_items.aggregate(
                total_qty=Sum('tot_qty'),
                subtotal=Sum(F('tot_qty') * F('unit_price')),
                grand_total=Sum('tot_amt')
            )
            po.total_quantity = aggregate['total_qty'] or 0
            po.grand_total = aggregate['grand_total'] or Decimal('0')
            po.save(update_fields=['total_quantity', 'grand_total'])
            
            remaining_budget = get_vendor_remaining_budget(po.vendor, exclude_po_id=po.id, include_draft_po_id=po.id) if po.vendor else Decimal('0')
                
            return JsonResponse({
                'success': True,
                'po_number': po.po_number,
                'totals': {
                    'total_items': po.total_quantity,
                    'subtotal': float(aggregate['subtotal'] or 0),
                    'grand_total': float(po.grand_total),
                    'remaining_budget': float(remaining_budget)
                }
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def preview_po(request):
    user = get_current_user(request)
    po_id = request.GET.get('po_id')
    if po_id:
        try:
            po = PurchaseOrder.objects.get(id=po_id)
        except (PurchaseOrder.DoesNotExist, ValueError):
            po = None
    else:
        po = PurchaseOrder.objects.filter(created_by=user, is_draft=True).first()
        if not po:
            po = PurchaseOrder.objects.filter(created_by=user).order_by('-updated_at').first()
            
    if not po:
        return render(request, 'po_sheet/print_po.html', {'error': 'No PO found'})
        
    po_items = po.items.all()
    subtotal = sum(item.tot_qty * item.unit_price for item in po_items)
    context = {
        'po': po,
        'po_items': po_items,
        'subtotal': subtotal,
        'today': datetime.now().strftime("%d/%m/%Y"),
        'print_time': datetime.now().strftime("%d/%m/%Y, %I:%M:%S %p")
    }
    return render(request, 'po_sheet/print_po.html', context)


@csrf_exempt
@login_required
def send_po(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        email = data.get('email')
        whatsapp = data.get('whatsapp')
        
        print(f"SIMULATING SEND: Email to {email}, WhatsApp to {whatsapp}")
        
        return JsonResponse({
            'success': True,
            'message': f"Purchase Order sent successfully via Email to {email} and WhatsApp to {whatsapp}!"
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def all_records(request):
    base_qs = (
        PurchaseOrder.objects
        .select_related('vendor', 'created_by')
        .prefetch_related('items', 'items__subcategory')
        .filter(is_draft=False)
        .order_by('-created_at')
    )

    if not request.user.is_staff:
        base_qs = base_qs.filter(created_by=request.user)

    qs = base_qs

    # Search
    search = request.GET.get('q', '').strip()
    if search:
        qs = qs.filter(
            Q(po_number__icontains=search) |
            Q(vendor__vendor_name__icontains=search) |
            Q(vendor__vendor_code__icontains=search) |
            Q(created_by__username__icontains=search)
        )

    # Filters
    vendor_filter = request.GET.get('vendor', '').strip()
    if vendor_filter:
        qs = qs.filter(vendor__vendor_code=vendor_filter)

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if date_from:
        qs = qs.filter(po_date__gte=date_from)
    if date_to:
        qs = qs.filter(po_date__lte=date_to)

    vendors = (
        base_qs
        .values('vendor__vendor_code', 'vendor__vendor_name')
        .distinct()
        .order_by('vendor__vendor_name')
    )

    return render(request, 'po_sheet/all_records.html', {
        'records': qs,
        'search': search,
        'vendor_filter': vendor_filter,
        'date_from': date_from,
        'date_to': date_to,
        'vendors': vendors,
        'total': qs.count(),
        'is_staff': request.user.is_staff,
    })


@login_required
def size_manager(request):
    return render(request, 'po_sheet/size_manager.html', {
        'all_subcategories': [],
    })


@login_required
def get_subcategory_sizes(request, subcategory_id):
    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
    except (SubCategory.DoesNotExist, ValueError):
        subcategory = SubCategory.objects.filter(name=subcategory_id).first()
        
    if not subcategory:
        return JsonResponse({'success': True, 'sizes': []})
        
    sizes = SubCategorySize.objects.filter(subcategory=subcategory).order_by('id')
    size_list = [{'id': s.id, 'name': s.name} for s in sizes]
    return JsonResponse({'success': True, 'sizes': size_list})


@csrf_exempt
@login_required
def add_subcategory_sizes(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        subcategory_id = data.get('subcategory_id')
        sizes = data.get('sizes', [])
        
        try:
            subcategory = SubCategory.objects.get(id=subcategory_id)
        except (SubCategory.DoesNotExist, ValueError):
            subcategory, _ = SubCategory.objects.get_or_create(
                name=subcategory_id,
            )
        
        for name in sizes:
            name = name.strip()
            if name:
                SubCategorySize.objects.get_or_create(subcategory=subcategory, name=name)
                
        # Return updated list
        all_sizes = SubCategorySize.objects.filter(subcategory=subcategory).order_by('id')
        size_list = [{'id': s.id, 'name': s.name} for s in all_sizes]
        return JsonResponse({'success': True, 'sizes': size_list})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt
@login_required
def remove_subcategory_size(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        subcategory_id = data.get('subcategory_id')
        size_id = data.get('size_id')
        
        try:
            subcategory = SubCategory.objects.get(id=subcategory_id)
        except (SubCategory.DoesNotExist, ValueError):
            subcategory = SubCategory.objects.filter(name=subcategory_id).first()
        if not subcategory:
            return JsonResponse({'success': False, 'error': 'Subcategory not found'})
        size = get_object_or_404(SubCategorySize, id=size_id, subcategory=subcategory)
        size.delete()
        
        # Return updated list
        all_sizes = SubCategorySize.objects.filter(subcategory=subcategory).order_by('id')
        size_list = [{'id': s.id, 'name': s.name} for s in all_sizes]
        return JsonResponse({'success': True, 'sizes': size_list})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def manage_users(request):
    if not request.user.is_staff:
        messages.error(request, 'Only administrators can manage users')
        return redirect('po_sheet')

    from django.contrib.auth.models import User
    
    if request.method == 'POST':
        action = request.POST.get('action')
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        role = request.POST.get('role', 'buyer')
        is_staff = (role == 'admin')
        is_active = 'is_active' in request.POST
        
        if action == 'create':
            if not username or not password:
                messages.error(request, 'Username and Password are required')
            elif User.objects.filter(username=username).exists():
                messages.error(request, f"User '{username}' already exists")
            else:
                try:
                    user = User.objects.create_user(
                        username=username,
                        password=password,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        is_staff=is_staff,
                        is_active=is_active
                    )
                    messages.success(request, f"User '{username}' successfully created")
                except Exception as e:
                    messages.error(request, f"Error creating user: {str(e)}")
            return redirect('manage_users')
            
        elif action == 'edit':
            user_id = request.POST.get('user_id')
            user_to_edit = get_object_or_404(User, id=user_id)
            
            # Username check if changed
            if username and username != user_to_edit.username:
                if User.objects.filter(username=username).exclude(id=user_id).exists():
                    messages.error(request, f"User '{username}' already exists")
                    return redirect('manage_users')
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
                messages.success(request, f"User '{user_to_edit.username}' successfully updated")
            except Exception as e:
                messages.error(request, f"Error updating user: {str(e)}")
            return redirect('manage_users')

    users = User.objects.all().order_by('-date_joined')
    return render(request, 'po_sheet/manage_users.html', {
        'users': users
    })


@login_required
def delete_user(request, user_id):
    if not request.user.is_staff:
        messages.error(request, 'Only administrators can manage users')
        return redirect('po_sheet')
        
    from django.contrib.auth.models import User
    user_to_delete = get_object_or_404(User, id=user_id)
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own account")
    else:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"User '{username}' successfully deleted")
    return redirect('manage_users')


@login_required
def delete_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    # Check permissions: must be staff or the creator
    if not request.user.is_staff and po.created_by != request.user:
        messages.error(request, "You do not have permission to delete this Purchase Order.")
        return redirect('all_records')
        
    po_number = po.po_number
    try:
        po.delete()
        messages.success(request, f"Purchase Order {po_number} successfully deleted.")
    except Exception as e:
        messages.error(request, f"Error deleting Purchase Order: {str(e)}")
        
    return redirect('all_records')


import csv
from django.http import HttpResponse

@login_required
def export_po_csv(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    # Check permissions: must be staff or the creator
    if not request.user.is_staff and po.created_by != request.user:
        messages.error(request, "You do not have permission to export this Purchase Order.")
        return redirect('all_records')
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{po.po_number}_Full_Export.csv"'
    
    writer = csv.writer(response)
    
    # Write PO Header Data (All fields from PO Model)
    writer.writerow([
        "PO Number", "PO Date", "PO Type", "Season", "Buyer", "Agent", 
        "Vendor Name", "Vendor Code", "Total Quantity", "Grand Total", 
        "Status", "Notes", "Delivery Schedules", "Created By", "Created At", "Updated At"
    ])
    
    writer.writerow([
        po.po_number,
        po.po_date,
        po.po_type,
        po.season,
        po.buyer.name if po.buyer else "",
        po.agent,
        po.vendor.vendor_name if po.vendor else "",
        po.vendor.vendor_code if po.vendor else "",
        po.total_quantity,
        po.grand_total,
        "Draft" if po.is_draft else "Saved",
        po.notes,
        po.delivery_schedules,
        po.created_by.username if po.created_by else "",
        po.created_at.strftime("%Y-%m-%d %H:%M:%S") if po.created_at else "",
        po.updated_at.strftime("%Y-%m-%d %H:%M:%S") if po.updated_at else ""
    ])
    
    writer.writerow([]) # Empty row for spacing
    
    # Write PO Items (All fields from PurchaseOrderItem Model)
    writer.writerow([
        "Item #", "SubCategory Name", "CH4 Code", "Item Type", "Order Qty", 
        "Total Qty", "Unit Price", "Discount %", "Total Amount", "Sizes Allocation"
    ])
    
    items = po.items.all()
    for index, item in enumerate(items, 1):
        # Format sizes beautifully
        sizes = item.size_allocations or {}
        size_str = " | ".join([f"{k}:{v}" for k, v in sizes.items()])
        
        writer.writerow([
            index,
            item.subcategory.name if item.subcategory else "",
            item.subcategory.ch4_code if item.subcategory else "",
            item.item_type,
            item.order_qty,
            item.tot_qty,
            item.unit_price,
            item.discount_percentage,
            item.tot_amt,
            size_str
        ])
        
    return response

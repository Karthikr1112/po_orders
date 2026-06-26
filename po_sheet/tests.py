from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from po_sheet.models import Vendor, Buyer, SubCategory, PurchaseOrder, PurchaseOrderItem, SubCategoryPriceRange
from po_sheet.views import get_subcategory_remaining_budget

class POTotalsAndBudgetTests(TransactionTestCase):
    def setUp(self):
        # Create user
        self.user = User.objects.create_user(username='buyer1', password='password123')
        
        # Create buyer
        self.buyer = Buyer.objects.create(name='Jeyachandran Buyer')
        
        # Create vendor
        self.vendor = Vendor.objects.create(
            vendor_code='V001',
            vendor_name='Premium Vendor Ltd',
            gst_number='33AAAAA0000A1Z5',
            city='Chennai'
        )
        
        # Create SubCategory
        self.subcategory = SubCategory.objects.create(
            name="Mens Shirt",
            ch4_code="MS001"
        )

        # Create SubCategoryPriceRange for the SubCategory (limit = 100000 units)
        self.price_range = SubCategoryPriceRange.objects.create(
            subcategory=self.subcategory,
            sales_from_range=Decimal('0.00'),
            sales_to_range=Decimal('10000.00'),
            buying_from_range=Decimal('0.00'),
            buying_to_range=Decimal('10000.00'),
            approved_amount=Decimal('100000.00'),
            approved_quantity=100000
        )

    def test_purchase_order_item_signals(self):
        """Test that adding/modifying items updates PurchaseOrder totals automatically via signals"""
        po = PurchaseOrder.objects.create(
            po_number='PO-TEST-001',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        
        # Add item
        item = PurchaseOrderItem.objects.create(
            purchase_order=po,
            subcategory=self.subcategory,
            item_type='Fresh',
            order_qty=12,
            unit_price=Decimal('500.00'),
            discount_percentage=Decimal('10.00')
        )
        
        # Save updates Tot Qty = order_qty = 12
        # Tot Amt = 12 * 500 * (1 - 0.10) = 5400.00
        self.assertEqual(item.tot_qty, 12)
        self.assertEqual(item.tot_amt, Decimal('5400.00'))
        
        # Reload PO
        po.refresh_from_db()
        self.assertEqual(po.total_quantity, 12)
        self.assertEqual(po.grand_total, Decimal('5400.00'))
 
    def test_remaining_budget_calculation(self):
        """Test that get_subcategory_remaining_budget subtracts only pending/approved POs, and handles draft correctly"""
        po1 = PurchaseOrder.objects.create(
            po_number='PO-TEST-002',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=False,
            grand_total=Decimal('20000.00'),
            total_quantity=40
        )
        PurchaseOrderItem.objects.create(
            purchase_order=po1,
            subcategory=self.subcategory,
            item_type='Fresh',
            order_qty=40,
            unit_price=Decimal('1.00')
        )
        
        # Budget approved amount = 100,000
        # Spent approved = 40 units
        # Remaining should be 99,960
        remaining = get_subcategory_remaining_budget(self.subcategory)
        self.assertEqual(remaining, Decimal('99960.00'))
        
        # Draft PO shouldn't count by default
        po_draft = PurchaseOrder.objects.create(
            po_number='PO-TEST-003',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True,
            grand_total=Decimal('5000.00'),
            total_quantity=10
        )
        PurchaseOrderItem.objects.create(
            purchase_order=po_draft,
            subcategory=self.subcategory,
            item_type='Fresh',
            order_qty=10,
            unit_price=Decimal('1.00')
        )
        
        remaining = get_subcategory_remaining_budget(self.subcategory)
        self.assertEqual(remaining, Decimal('99960.00'))
        
        # But if explicitly included (for example when showing remaining budget in draft page)
        remaining_with_draft = get_subcategory_remaining_budget(self.subcategory, include_draft_po_id=po_draft.id)
        self.assertEqual(remaining_with_draft, Decimal('99950.00'))

    def test_save_po_budget_constraints(self):
        """Test that save_po view prevents saving PO when budget or qty limit is exceeded"""
        from po_sheet.models import SubCategory, SubCategoryPriceRange
        import json
        
        self.client.login(username='buyer1', password='password123')
        
        # Create a dedicated subcategory for constraint validation to prevent price range overlap
        subcat_constraint = SubCategory.objects.create(name="Constraint Subcat")
        
        # Create a price range for subcat_constraint: approved amount 1000, approved quantity 10
        pr = SubCategoryPriceRange.objects.create(
            subcategory=subcat_constraint,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('100.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('100.00'),
            approved_amount=Decimal('1000.00'),
            approved_quantity=10
        )
        
        # 1. Create a draft PO
        po = PurchaseOrder.objects.create(
            po_number='PO-TEST-004',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        
        # 2. Try to save an item with price=50, qty=5. (Total = 250, fits in 1000 budget and 10 qty)
        payload = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Summer 2026",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_constraint.id,
                    "item_type": "Fresh",
                    "order_qty": 5,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        
        response = self.client.post(
            '/save-po/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertTrue(res_data['success'])
        
        # 3. Create another draft PO to try exceeding budget
        po2 = PurchaseOrder.objects.create(
            po_number='PO-TEST-005',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        
        # Try to save with qty 15 (exceeds total approved quantity of 10, since 5 is already submitted/saved and 15 more is requested, total 20)
        payload_exceed_qty = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Summer 2026",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_constraint.id,
                    "item_type": "Fresh",
                    "order_qty": 15,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        
        response = self.client.post(
            '/save-po/',
            data=json.dumps(payload_exceed_qty),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertFalse(res_data['success'])
        self.assertIn("Quantity limit reached", res_data['error'])
        
        # Try to save with price 90, qty 10 (exceeds budget: total spent so far 250 + 900 = 1150, approved 1000)
        payload_exceed_budget = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Summer 2026",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_constraint.id,
                    "item_type": "Fresh",
                    "order_qty": 10,
                    "unit_price": 90.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        
        response = self.client.post(
            '/save-po/',
            data=json.dumps(payload_exceed_budget),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertFalse(res_data['success'])
        self.assertIn("Budget limit reached", res_data['error'])

    def test_save_po_without_budget_is_blocked(self):
        """Test that save_po view prevents saving PO when subcategory has no budget/qty allocated"""
        import json
        self.client.login(username='buyer1', password='password123')
        
        # Create a subcategory and a price range with 0 budget and 0 quantity
        subcat_nobudget = SubCategory.objects.create(name="No Budget Subcat")
        SubCategoryPriceRange.objects.create(
            subcategory=subcat_nobudget,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('100.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('100.00'),
            approved_amount=Decimal('0.00'),
            approved_quantity=0
        )
        
        # Create draft PO
        po = PurchaseOrder.objects.create(
            po_number='PO-TEST-006',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        
        payload = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Summer 2026",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_nobudget.id,
                    "item_type": "Fresh",
                    "order_qty": 5,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        
        response = self.client.post(
            '/save-po/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertFalse(res_data['success'])
        self.assertIn("does not have an approved budget or quantity", res_data['error'])


class SubCategorySizeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin', password='password123', is_staff=True)
        self.client.login(username='admin', password='password123')
        self.subcategory = SubCategory.objects.create(name='Shirts')

    def test_add_get_remove_sizes(self):
        import json
        # Add sizes
        response = self.client.post(
            '/add-subcategory-sizes/',
            data=json.dumps({'subcategory_id': self.subcategory.id, 'sizes': ['XL', 'L']}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['sizes']), 2)
        self.assertEqual(data['sizes'][0]['name'], 'XL')

        # Get sizes
        response = self.client.get(f'/get-subcategory-sizes/{self.subcategory.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['sizes']), 2)

        # Remove size
        size_id = data['sizes'][0]['id']
        response = self.client.post(
            '/remove-subcategory-size/',
            data=json.dumps({'subcategory_id': self.subcategory.id, 'size_id': size_id}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['sizes']), 1)
        self.assertEqual(data['sizes'][0]['name'], 'L')

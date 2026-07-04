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

    def test_season_specific_budget_constraints(self):
        """Test that budget checks are scoped to specific seasons"""
        from po_sheet.models import Season
        import json
        self.client.login(username='buyer1', password='password123')

        season_onam = Season.objects.create(name="Onam")
        season_diwali = Season.objects.create(name="Diwali")

        subcat_season = SubCategory.objects.create(name="Seasonal Subcat")

        # Range for Onam: Approved amount 1000, qty 10
        pr_onam = SubCategoryPriceRange.objects.create(
            subcategory=subcat_season,
            season=season_onam,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('100.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('100.00'),
            approved_amount=Decimal('1000.00'),
            approved_quantity=10
        )

        # Range for Diwali: Approved amount 500, qty 5
        pr_diwali = SubCategoryPriceRange.objects.create(
            subcategory=subcat_season,
            season=season_diwali,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('100.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('100.00'),
            approved_amount=Decimal('500.00'),
            approved_quantity=5
        )

        # 1. Create a draft PO under Onam
        po = PurchaseOrder.objects.create(
            po_number='PO-TEST-SEASON-1',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )

        # Save with qty 8, price 50 (Total 400). Fits under Onam (Limit 1000 amt, 10 qty)
        payload = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Onam",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_season.id,
                    "item_type": "Fresh",
                    "order_qty": 8,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        response = self.client.post('/save-po/', data=json.dumps(payload), content_type='application/json')
        self.assertTrue(response.json()['success'])

        # 2. Try to save another PO under Diwali with qty 4 (Total 200). Fits under Diwali (Limit 500 amt, 5 qty).
        # Note: Even though total across Onam and Diwali is 8+4=12 (which is > 10 Onam and > 5 Diwali limit), they are separate seasons!
        po2 = PurchaseOrder.objects.create(
            po_number='PO-TEST-SEASON-2',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        payload_diwali = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Diwali",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_season.id,
                    "item_type": "Fresh",
                    "order_qty": 4,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        response2 = self.client.post('/save-po/', data=json.dumps(payload_diwali), content_type='application/json')
        self.assertTrue(response2.json()['success'])

        # 3. Try to exceed Diwali limit with a third PO under Diwali: total Diwali qty would be 4 + 2 = 6 (> 5 limit)
        po3 = PurchaseOrder.objects.create(
            po_number='PO-TEST-SEASON-3',
            buyer=self.buyer,
            vendor=self.vendor,
            created_by=self.user,
            is_draft=True
        )
        payload_diwali_exceed = {
            "buyer": self.buyer.id,
            "agent": "Test Agent",
            "notes": "Test Notes",
            "delivery_schedules": [],
            "po_type": "Fresh",
            "season": "Diwali",
            "po_date": "2026-06-26",
            "items": [
                {
                    "subcategory_id": subcat_season.id,
                    "item_type": "Fresh",
                    "order_qty": 2,
                    "unit_price": 50.0,
                    "discount_percentage": 0.0,
                    "size_allocations": {}
                }
            ]
        }
        response3 = self.client.post('/save-po/', data=json.dumps(payload_diwali_exceed), content_type='application/json')
        self.assertFalse(response3.json()['success'])
        self.assertIn("Quantity limit reached", response3.json()['error'])

    def test_get_or_sync_subcategory_price_ranges_cloning(self):
        """Test that get_or_sync_subcategory_price_ranges clones existing ranges from other seasons"""
        from po_sheet.models import Season
        from po_sheet.views import get_or_sync_subcategory_price_ranges

        subcat = SubCategory.objects.create(name="Cloning Test Subcat")
        season_onam = Season.objects.create(name="Onam")
        season_diwali = Season.objects.create(name="Diwali")

        # 1. Create a price range for Onam (diwali has none yet)
        SubCategoryPriceRange.objects.create(
            subcategory=subcat,
            season=season_onam,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('500.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('500.00'),
            approved_amount=Decimal('1000.00'),
            approved_quantity=100
        )

        SubCategoryPriceRange.objects.create(
            subcategory=subcat,
            season=season_onam,
            sales_from_range=Decimal('501.00'),
            sales_to_range=Decimal('1000.00'),
            buying_from_range=Decimal('501.00'),
            buying_to_range=Decimal('1000.00'),
            approved_amount=Decimal('2000.00'),
            approved_quantity=200
        )

        # 2. Call get_or_sync_subcategory_price_ranges for Diwali (which has 0 ranges initially)
        ranges = get_or_sync_subcategory_price_ranges(subcat, season=season_diwali)

        # 3. Assert that Diwali now has 2 cloned ranges matching Onam's sales/buying range intervals
        # but with approved_amount = 0 and approved_quantity = 0
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0].sales_from_range, Decimal('10.00'))
        self.assertEqual(ranges[0].sales_to_range, Decimal('500.00'))
        self.assertEqual(ranges[0].approved_amount, Decimal('0.00'))
        self.assertEqual(ranges[0].approved_quantity, 0)
        self.assertEqual(ranges[0].season, season_diwali)

        self.assertEqual(ranges[1].sales_from_range, Decimal('501.00'))
        self.assertEqual(ranges[1].sales_to_range, Decimal('1000.00'))
        self.assertEqual(ranges[1].approved_amount, Decimal('0.00'))
        self.assertEqual(ranges[1].approved_quantity, 0)
        self.assertEqual(ranges[1].season, season_diwali)

    def test_get_or_sync_subcategory_price_ranges_placeholder_replacement(self):
        """Test that get_or_sync_subcategory_price_ranges replaces a 0-0 placeholder if other seasons have actual price ranges"""
        from po_sheet.models import Season
        from po_sheet.views import get_or_sync_subcategory_price_ranges

        subcat = SubCategory.objects.create(name="Placeholder Replacement Test")
        season_onam = Season.objects.create(name="Onam")
        season_diwali = Season.objects.create(name="Diwali")

        # 1. Create a price range for Onam
        SubCategoryPriceRange.objects.create(
            subcategory=subcat,
            season=season_onam,
            sales_from_range=Decimal('10.00'),
            sales_to_range=Decimal('500.00'),
            buying_from_range=Decimal('10.00'),
            buying_to_range=Decimal('500.00'),
            approved_amount=Decimal('1000.00'),
            approved_quantity=100
        )

        # 2. Create a placeholder 0-0 range for Diwali
        placeholder = SubCategoryPriceRange.objects.create(
            subcategory=subcat,
            season=season_diwali,
            sales_from_range=Decimal('0.00'),
            sales_to_range=Decimal('0.00'),
            buying_from_range=Decimal('0.00'),
            buying_to_range=Decimal('0.00'),
            approved_amount=Decimal('0.00'),
            approved_quantity=0
        )

        # 3. Call get_or_sync_subcategory_price_ranges for Diwali. It should detect the placeholder, delete it, and clone from Onam.
        ranges = get_or_sync_subcategory_price_ranges(subcat, season=season_diwali)

        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].sales_from_range, Decimal('10.00'))
        self.assertEqual(ranges[0].sales_to_range, Decimal('500.00'))
        self.assertEqual(ranges[0].season, season_diwali)

        # Verify that the original placeholder was indeed deleted from the database
        self.assertFalse(SubCategoryPriceRange.objects.filter(id=placeholder.id).exists())


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

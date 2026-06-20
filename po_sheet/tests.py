from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from po_sheet.models import Vendor, Buyer, SubCategory, PurchaseOrder, PurchaseOrderItem, AdminBudget
from po_sheet.views import get_subcategory_remaining_budget

class POTotalsAndBudgetTests(TestCase):
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

        # Create Admin Budget for the SubCategory (limit = 100000 units)
        self.budget = AdminBudget.objects.create(
            subcategory=self.subcategory,
            approved_amount=Decimal('100000.00'),
            approved_by=self.user,
            notes='Initial Test Budget'
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

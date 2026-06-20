from django.core.management.base import BaseCommand
from decimal import Decimal
from django.db.models import Sum, F
from po_sheet.models import PurchaseOrder


class Command(BaseCommand):
    help = 'Recalculate and update all Purchase Order totals'

    def add_arguments(self, parser):
        parser.add_argument(
            '--po-number',
            type=str,
            help='Specific PO number to recalculate (optional)',
        )

    def handle(self, *args, **options):
        po_number = options.get('po_number')
        
        if po_number:
            pos = PurchaseOrder.objects.filter(po_number=po_number)
        else:
            pos = PurchaseOrder.objects.all()
        
        updated_count = 0
        for po in pos:
            po_items = po.items.all()
            
            if po_items.exists():
                aggregate = po_items.aggregate(
                    total_items=Sum('tot_qty'),
                    subtotal=Sum(F('tot_qty') * F('unit_price')),
                    grand_total=Sum('tot_amt')
                )
                totals = {
                    'items': aggregate['total_items'] or 0,
                    'subtotal': aggregate['subtotal'] or Decimal('0'),
                    'grand_total': aggregate['grand_total'] or Decimal('0'),
                }
            else:
                totals = {
                    'items': 0,
                    'subtotal': Decimal('0'),
                    'grand_total': Decimal('0'),
                }
            
            # Update PO
            po.total_quantity = totals['items']
            po.grand_total = totals['grand_total']
            po.save(update_fields=['total_quantity', 'grand_total'])
            updated_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated {po.po_number}: Grand Total = ₹{totals["grand_total"]}'
                )
            )
        
        self.stdout.write(
            self.style.SUCCESS(f'\nSuccessfully updated {updated_count} Purchase Orders')
        )

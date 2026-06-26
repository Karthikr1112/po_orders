import os
import openpyxl
from django.core.management.base import BaseCommand
from django.conf import settings
from po_sheet.models import Buyer, SubCategory


class Command(BaseCommand):
    help = 'Import buyers and subcategories from buyer.xlsx'

    def add_arguments(self, parser):
        parser.add_argument(
            '--resync',
            action='store_true',
            help='Clear all existing buyer-subcategory links before importing (full resync)',
        )

    def handle(self, *args, **options):
        file_path = os.path.join(settings.BASE_DIR, 'buyer.xlsx')
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        self.stdout.write(f"Loading {file_path}...")
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        # --resync: wipe all M2M links first so removed rows are cleaned up
        if options['resync']:
            SubCategory.buyers.through.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared all existing buyer-subcategory links."))

        # Read Excel into memory, deduplicate by (subcat_name, buyer_name)
        excel_rows = []
        seen = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            subcat_name = str(row[0]).strip() if row[0] else ''
            subcat_code = str(row[1]).strip() if row[1] is not None else ''
            raw_buyer   = row[3]
            buyer_name  = str(raw_buyer).strip() if raw_buyer and str(raw_buyer).strip() not in ('0', '') else ''

            if not subcat_name:
                continue

            key = (subcat_name, buyer_name)
            if key in seen:
                continue
            seen.add(key)
            excel_rows.append((subcat_name, subcat_code, buyer_name))

        created_subcats = 0
        updated_codes   = 0
        created_buyers  = 0
        linked_count    = 0
        no_buyer_count  = 0

        for subcat_name, subcat_code, buyer_name in excel_rows:
            # Always upsert the subcategory
            subcat, sc_created = SubCategory.objects.get_or_create(
                name=subcat_name,
                defaults={'ch4_code': subcat_code}
            )
            if sc_created:
                created_subcats += 1
            elif subcat_code and subcat.ch4_code != subcat_code:
                subcat.ch4_code = subcat_code
                subcat.save(update_fields=['ch4_code'])
                updated_codes += 1

            # Link buyer only when a real name exists
            if buyer_name:
                buyer, b_created = Buyer.objects.get_or_create(name=buyer_name)
                if b_created:
                    created_buyers += 1
                if not subcat.buyers.filter(id=buyer.id).exists():
                    subcat.buyers.add(buyer)
                    linked_count += 1
            else:
                no_buyer_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. "
            f"Subcategories: {created_subcats} created, {updated_codes} code updated. "
            f"Buyers: {created_buyers} created, {linked_count} links added. "
            f"{no_buyer_count} rows had no buyer (subcategory still created)."
        ))

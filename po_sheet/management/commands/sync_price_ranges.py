import MySQLdb
import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from po_sheet.models import SubCategory, SubCategoryPriceRange

logger = logging.getLogger("sync_price_ranges")


class Command(BaseCommand):
    help = 'Sync subcategory price ranges from external MySQL database (mis_db)'

    def handle(self, *args, **options):
        self.stdout.write("Caching local subcategories...")
        local_subcats = list(SubCategory.objects.all())
        subcat_by_code = {sc.ch4_code: sc for sc in local_subcats if sc.ch4_code}
        subcat_by_name = {sc.name.lower(): sc for sc in local_subcats}

        self.stdout.write("Caching existing local price ranges...")
        # Map composite key (subcategory_id, sales_from_range, sales_to_range) -> SubCategoryPriceRange object
        local_ranges = {
            (pr.subcategory_id, pr.sales_from_range, pr.sales_to_range): pr
            for pr in SubCategoryPriceRange.objects.filter(season__isnull=True)
        }

        self.stdout.write("Connecting to external MySQL (mis_db)...")
        conn = None
        try:
            conn = MySQLdb.connect(
                host='192.168.2.77', user='mis_user',
                password='Leoni', db='mis_db', charset='utf8mb4'
            )
            cursor = conn.cursor()

            # DISTINCT eliminates query duplicate rows
            cursor.execute("""
                SELECT DISTINCT s.code, s.name, p.from_range, p.to_range
                FROM mis_db.inventory_subcategory s
                JOIN mis_db.inventory_pricerange p ON s.id = p.sub_category_id
                ORDER BY s.code, p.from_range
            """)
            rows = cursor.fetchall()
            self.stdout.write(f"Fetched {len(rows)} DISTINCT ranges from external DB.")
            logger.info(f"Fetched {len(rows)} DISTINCT ranges from external DB.")

        except Exception as e:
            error_msg = f"External DB connection/query error: {e}"
            self.stdout.write(self.style.ERROR(error_msg))
            logger.error(error_msg)
            return
        finally:
            if conn:
                conn.close()

        to_create = []
        to_update_ranges = []
        to_update_subcats = set()

        created_count = 0
        skipped_count = 0
        updated_subcat_count = 0
        updated_range_count = 0
        no_match = 0

        # Wrap modifications in a database transaction to ensure atomicity
        try:
            with transaction.atomic():
                for code, name, from_range, to_range in rows:
                    code_str = str(code) if code else ''

                    # 1. Match local subcategory
                    subcat = subcat_by_code.get(code_str)
                    if not subcat and name:
                        subcat = subcat_by_name.get(name.lower())

                    if not subcat:
                        no_match += 1
                        continue

                    # 2. Check if subcategory details changed in external DB (Sync changes back)
                    subcat_changed = False
                    if code_str and subcat.ch4_code != code_str:
                        subcat.ch4_code = code_str
                        subcat_changed = True
                    if name and subcat.name.lower() != name.lower():
                        subcat.name = name
                        subcat_changed = True

                    if subcat_changed:
                        to_update_subcats.add(subcat)

                    # 3. Format ranges and verify price range entry
                    sf = Decimal(str(from_range))
                    st = Decimal(str(to_range))
                    key = (subcat.id, sf, st)

                    if key in local_ranges:
                        # Record exists. Check if subcat_code has changed
                        pr = local_ranges[key]
                        if pr.subcat_code != code_str:
                            pr.subcat_code = code_str
                            to_update_ranges.append(pr)
                            updated_range_count += 1
                        else:
                            skipped_count += 1
                        continue

                    # 4. Record is new: add to batch creation
                    new_pr = SubCategoryPriceRange(
                        subcategory=subcat,
                        sales_from_range=sf,
                        sales_to_range=st,
                        buying_from_range=Decimal('0.00'),
                        buying_to_range=Decimal('0.00'),
                        subcat_code=code_str,
                    )
                    to_create.append(new_pr)
                    local_ranges[key] = new_pr  # Cache to prevent duplicate items within same batch

                    if len(to_create) >= 500:
                        SubCategoryPriceRange.objects.bulk_create(to_create, ignore_conflicts=True)
                        created_count += len(to_create)
                        to_create = []

                # Write remaining new objects
                if to_create:
                    SubCategoryPriceRange.objects.bulk_create(to_create, ignore_conflicts=True)
                    created_count += len(to_create)

                # Bulk write subcategory changes (e.g. name or code updates)
                if to_update_subcats:
                    SubCategory.objects.bulk_update(list(to_update_subcats), ['ch4_code', 'name'])
                    updated_subcat_count = len(to_update_subcats)

                # Bulk write modified price range fields
                if to_update_ranges:
                    SubCategoryPriceRange.objects.bulk_update(to_update_ranges, ['subcat_code'])

                # Ensure every local subcategory has at least a 0-0 placeholder
                subcats_with_ranges = {sid for sid, _, _ in local_ranges}
                defaults = []
                default_count = 0
                for sc in local_subcats:
                    key = (sc.id, Decimal('0.00'), Decimal('0.00'))
                    if sc.id not in subcats_with_ranges and key not in local_ranges:
                        defaults.append(SubCategoryPriceRange(
                            subcategory=sc,
                            sales_from_range=Decimal('0.00'),
                            sales_to_range=Decimal('0.00'),
                            buying_from_range=Decimal('0.00'),
                            buying_to_range=Decimal('0.00'),
                        ))
                        if len(defaults) >= 500:
                            SubCategoryPriceRange.objects.bulk_create(defaults, ignore_conflicts=True)
                            default_count += len(defaults)
                            defaults = []
                if defaults:
                    SubCategoryPriceRange.objects.bulk_create(defaults, ignore_conflicts=True)
                    default_count += len(defaults)

            success_msg = (
                f"Sync Completed successfully.\n"
                f"- Created {created_count} new price ranges.\n"
                f"- Skipped {skipped_count} existing price ranges.\n"
                f"- Updated {updated_range_count} price range codes.\n"
                f"- Updated {updated_subcat_count} subcategories.\n"
                f"- Added {default_count} default 0-0 placeholders.\n"
                f"- Skipped {no_match} external rows (no local matching subcategory)."
            )
            self.stdout.write(self.style.SUCCESS(success_msg))
            logger.info(success_msg)
            self.stdout.write(f"Total local price ranges now: {SubCategoryPriceRange.objects.count()}")

        except Exception as ex:
            error_msg = f"Database transaction failed: {ex}"
            self.stdout.write(self.style.ERROR(error_msg))
            logger.error(error_msg)

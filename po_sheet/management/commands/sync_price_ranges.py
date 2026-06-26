import MySQLdb
from decimal import Decimal
from django.core.management.base import BaseCommand
from po_sheet.models import SubCategory, SubCategoryPriceRange


class Command(BaseCommand):
    help = 'Sync subcategory price ranges from external MySQL database (mis_db)'

    def handle(self, *args, **options):
        self.stdout.write("Caching local subcategories...")
        local_subcats   = list(SubCategory.objects.all())
        subcat_by_code  = {sc.ch4_code: sc for sc in local_subcats if sc.ch4_code}
        subcat_by_name  = {sc.name.lower(): sc for sc in local_subcats}

        self.stdout.write("Caching existing local price ranges...")
        local_ranges = set(
            SubCategoryPriceRange.objects.values_list(
                'subcategory_id', 'sales_from_range', 'sales_to_range'
            )
        )

        self.stdout.write("Connecting to external MySQL (mis_db)...")
        conn = None
        try:
            conn = MySQLdb.connect(
                host='192.168.2.29', user='mis_user',
                passwd='Mis$2727', db='mis_db', charset='utf8mb4'
            )
            cursor = conn.cursor()

            # DISTINCT eliminates the 139 023-row duplicate problem
            cursor.execute("""
                SELECT DISTINCT s.code, s.name, p.from_range, p.to_range
                FROM mis_db.inventory_subcategory s
                JOIN mis_db.inventory_pricerange p ON s.id = p.sub_category_id
                ORDER BY s.code, p.from_range
            """)
            rows = cursor.fetchall()
            self.stdout.write(f"Fetched {len(rows)} DISTINCT ranges from external DB.")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"External DB error: {e}"))
            return
        finally:
            if conn:
                conn.close()

        to_create     = []
        created_count = 0
        skipped_count = 0
        no_match      = 0

        for code, name, from_range, to_range in rows:
            # Match local subcategory by code first, then name
            subcat = subcat_by_code.get(str(code) if code else '')
            if not subcat and name:
                subcat = subcat_by_name.get(name.lower())
            if not subcat:
                no_match += 1
                continue

            sf = Decimal(str(from_range))
            st = Decimal(str(to_range))
            key = (subcat.id, sf, st)

            if key in local_ranges:
                skipped_count += 1
                continue

            local_ranges.add(key)   # prevent duplicates within this batch
            to_create.append(SubCategoryPriceRange(
                subcategory=subcat,
                sales_from_range=sf,
                sales_to_range=st,
                buying_from_range=Decimal('0.00'),
                buying_to_range=Decimal('0.00'),
                subcat_code=str(code) if code else '',
            ))

            if len(to_create) >= 500:
                SubCategoryPriceRange.objects.bulk_create(to_create, ignore_conflicts=True)
                created_count += len(to_create)
                to_create = []

        if to_create:
            SubCategoryPriceRange.objects.bulk_create(to_create, ignore_conflicts=True)
            created_count += len(to_create)

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

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created_count} new ranges, "
            f"{skipped_count} already existed, "
            f"{no_match} external rows had no local match, "
            f"{default_count} default 0-0 placeholders added."
        ))
        self.stdout.write(f"Total local price ranges now: {SubCategoryPriceRange.objects.count()}")

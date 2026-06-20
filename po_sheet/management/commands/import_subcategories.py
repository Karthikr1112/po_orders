import csv
from django.core.management.base import BaseCommand
from po_sheet.models import Category, SubCategory


class Command(BaseCommand):
    help = "Import CH3/CH4 category hierarchy from TAB-separated CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to TAB-separated CSV file'
        )

    def handle(self, *args, **kwargs):
        csv_file = kwargs['csv_file']

        try:
            with open(csv_file, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter='\t')

                # Clean header names
                reader.fieldnames = [h.strip() for h in reader.fieldnames]

                required_columns = [
                    'Category',
                    'CH4', 'SubCategory'
                ]

                for col in required_columns:
                    if col not in reader.fieldnames:
                        self.stderr.write(self.style.ERROR(f"Missing column: {col}"))
                        self.stderr.write(f"Found columns: {reader.fieldnames}")
                        return

                created_cat = 0
                created_sub = 0

                for row in reader:
                    category_name = row['Category'].strip()
                    ch4 = row['CH4'].strip()
                    subcategory_name = row['SubCategory'].strip()

                    if not category_name or not subcategory_name:
                        continue

                    category, cat_created = Category.objects.get_or_create(
                        name=category_name
                    )
                    if cat_created:
                        created_cat += 1

                    ch4_code = str(ch4).strip() if ch4 else None

                    subcategory, sub_created = SubCategory.objects.get_or_create(
                        category=category,
                        name=subcategory_name,
                        defaults={
                            'ch4_code': ch4_code,
                        }
                    )
                    if not sub_created:
                        if subcategory.ch4_code != ch4_code:
                            subcategory.ch4_code = ch4_code
                            subcategory.save(update_fields=['ch4_code'])
                    else:
                        created_sub += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Import completed. New Categories: {created_cat}, Subcategories: {created_sub}"
                    )
                )

        except FileNotFoundError:
            self.stderr.write(self.style.ERROR("CSV file not found"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {e}"))

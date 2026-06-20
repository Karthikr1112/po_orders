from django.core.management.base import BaseCommand
from po_sheet.models import SubCategory, Category

class Command(BaseCommand):
    help = "Delete all Categories and SubCategories"

    def handle(self, *args, **kwargs):
        sub_count = SubCategory.objects.count()
        cat_count = Category.objects.count()

        SubCategory.objects.all().delete()
        Category.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Deleted {sub_count} SubCategories and {cat_count} Categories"
            )
        )

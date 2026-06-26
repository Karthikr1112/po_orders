from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("po_sheet", "0016_alter_subcategory_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="subcategorypricerange",
            name="approved_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14),
        ),
        migrations.AddField(
            model_name="subcategorypricerange",
            name="approved_quantity",
            field=models.PositiveIntegerField(default=0),
        ),
    ]

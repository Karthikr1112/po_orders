from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("po_sheet", "0017_subcategorypricerange_approved_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="subcategorypricerange",
            name="subcat_code",
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True),
        ),
    ]

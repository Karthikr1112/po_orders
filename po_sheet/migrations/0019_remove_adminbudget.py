from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('po_sheet', '0018_subcategorypricerange_subcat_code'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AdminBudget',
        ),
    ]

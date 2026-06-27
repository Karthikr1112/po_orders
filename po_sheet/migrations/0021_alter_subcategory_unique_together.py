from django.db import migrations


class Migration(migrations.Migration):
    """
    The server's makemigrations detected that the SubCategory unique_together
    still referenced the removed 'category' field in migration state.
    We update the state only — no database operation — because the 'category'
    column (and its constraint) was already dropped in migration 0011.
    """

    dependencies = [
        ('po_sheet', '0020_add_performance_indexes'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterUniqueTogether(
                    name='subcategory',
                    unique_together=set(),
                ),
            ],
        ),
    ]

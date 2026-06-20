from django.apps import AppConfig


class PoSheetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "po_sheet"

    def ready(self):
        import po_sheet.signals  # noqa: F401 — connect signal handlers

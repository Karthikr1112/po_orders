class MSSQLRouter:
    """
    Route Django ORM operations:
      - All app models  → MySQL ('default')
      - MSSQL is accessed via raw pyodbc only (no Django ORM models live there)
      - Migrations are never applied to MSSQL
    """

    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Both databases are internal; cross-DB FK references are intentional.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Never run migrations against the read-only SAP/MSSQL database.
        return db == "default"

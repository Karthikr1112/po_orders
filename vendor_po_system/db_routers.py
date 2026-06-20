class MSSQLRouter:
    """
    A router to control database operations, routing specific read operations 
    to the MSSQL database and all other operations to the default MySQL database.
    """
    
    # List the exact names of the models you want to read from MSSQL.
    # Currently empty so it doesn't crash your local views!
    mssql_models = []

    def db_for_read(self, model, **hints):
        """
        Directs read operations for specific models to the 'mssql' database.
        All other models read from the 'default' MySQL database.
        """
        if model.__name__ in self.mssql_models:
            return 'mssql'
        return 'default'

    def db_for_write(self, model, **hints):
        """
        All write operations always go to the 'default' MySQL database.
        MSSQL is strictly read-only.
        """
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow cross-database relations.
        """
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Prevent Django from trying to create tables (migrate) in the MSSQL database.
        All migrations should only happen on the default MySQL database.
        """
        if db == 'mssql':
            return False
        return True

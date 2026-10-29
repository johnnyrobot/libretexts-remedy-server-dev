"""Shared real SQLite intent-commit hard-exit injection for store/HTTP tests."""
import os


def exit_at_intent_commit(store, point):
    connect = store._connect
    class Connection:
        def __init__(self):
            self.connection, self.prepared = connect(), False
        def __enter__(self):
            self.connection.__enter__()
            return self
        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if sql.startswith("INSERT INTO submission_intents"):
                self.prepared = True
                if point == "db-before-commit":
                    os._exit(73)
            return result
        def __exit__(self, *args):
            result = self.connection.__exit__(*args)
            if self.prepared and point == "db-after-commit":
                os._exit(73)
            return result
    store._connect = Connection

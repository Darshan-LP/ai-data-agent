
from app.db import admin_engine


engine = admin_engine()

try:
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
        print("Admin connection: OK")
except Exception as exc:
    print(type(exc).__name__ + ":")
    print(str(exc).splitlines()[0])
finally:
    engine.dispose()

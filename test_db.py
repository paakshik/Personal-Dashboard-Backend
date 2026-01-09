# from sqlalchemy import create_engine, text
# from sqlalchemy.exc import SQLAlchemyError
# import sys
#
# # ✅ Your Render database URL
# DATABASE_URL = "postgresql://personal_dashboard_g49i_user:lgo8xLgAXKk8BbvmYbasx8OlL0he14Vd@dpg-d58h5phr0fns73f8g570-a.oregon-postgres.render.com/personal_dashboard_g49i"
#
#
# def test_database_connection():
#     """Test database connection with comprehensive error handling."""
#     print("🔌 Testing database connection...")
#
#     # Hide credentials in output - show only first 30 chars for safety
#     masked_url = DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL
#     print(f"Host: {masked_url}")
#
#     try:
#         # ✅ Create engine with connection pooling for better performance
#         engine = create_engine(
#             DATABASE_URL,
#             pool_pre_ping=True,  # Verify connections before using them
#             echo=False,  # Set to True for debugging SQL queries
#             connect_args={
#                 'connect_timeout': 10,  # 10 second timeout
#                 'application_name': 'db_test_tool'
#             }
#         )
#
#         print("🔄 Attempting to connect to database...")
#
#         # ✅ Use context manager for automatic connection handling
#         with engine.connect() as connection:
#             print("✅ SUCCESS! Database connection established.")
#
#             # ✅ Test with a simple query using text() wrapper (required for SQLAlchemy 2.0)
#             print("🔄 Executing test query...")
#
#             # Method 1: Using text() wrapper (standard SQLAlchemy 2.0 approach)
#             result = connection.execute(text("SELECT 1 as test_value, version() as db_version"))
#
#             # Fetch and display results
#             row = result.fetchone()
#             print(f"✅ Query execution successful!")
#             print(f"   Test value: {row.test_value}")
#             print(f"   PostgreSQL Version: {row.db_version.split(',')[0]}")
#
#             # ✅ Optional: Test actual table access if you have tables
#             try:
#                 # Try to list tables (if permissions allow)
#                 tables_result = connection.execute(text(
#                     "SELECT table_name FROM information_schema.tables "
#                     "WHERE table_schema = 'public' ORDER BY table_name LIMIT 5"
#                 ))
#                 tables = [row[0] for row in tables_result]
#                 if tables:
#                     print(f"📊 Found tables: {', '.join(tables)}")
#                 else:
#                     print("📊 No tables found in public schema")
#             except:
#                 pass  # Skip if user doesn't have permissions for this query
#
#         # ✅ Test connection pooling
#         print("🔄 Testing connection pool...")
#         with engine.connect() as conn2:
#             conn2.execute(text("SELECT 1"))
#         print("✅ Connection pool test passed.")
#
#         # ✅ Display connection info
#         print("\n" + "=" * 50)
#         print("🎉 DATABASE CONNECTION TEST PASSED!")
#         print("=" * 50)
#         print(f"• Connection URL: postgresql://...@{masked_url}")
#         print(f"• Driver: {engine.dialect.name}")
#         print(f"• Database: {engine.url.database}")
#         print(f"• Username: {engine.url.username}")
#         print("• Status: ✅ READY FOR USE")
#         print("=" * 50)
#
#         return True
#
#     except ImportError as e:
#         print(f"\n❌ DEPENDENCY ERROR!")
#         print(f"Missing package: {e}")
#         print("\n💡 Solution: Run: pip install sqlalchemy psycopg2-binary")
#         return False
#
#     except SQLAlchemyError as e:
#         print(f"\n❌ DATABASE ERROR!")
#         print(f"Error Type: {type(e).__name__}")
#         print(f"Error Details: {e}")
#
#         # Provide specific troubleshooting tips
#         print("\n🔧 TROUBLESHOOTING:")
#         print("1. Check if database is active on Render.com")
#         print("2. Verify external connections are enabled in Render settings")
#         print("3. Ensure your IP is whitelisted in Render")
#         print("4. Check database credentials")
#         print("5. Verify network connectivity to Render")
#
#         return False
#
#     except Exception as e:
#         print(f"\n❌ UNEXPECTED ERROR!")
#         print(f"Error: {type(e).__name__}: {e}")
#         return False
#
#
# if __name__ == "__main__":
#     success = test_database_connection()
#
#     if not success:
#         print("\n" + "!" * 50)
#         print("ACTION REQUIRED:")
#         print("1. Go to https://dashboard.render.com")
#         print("2. Select your PostgreSQL database")
#         print("3. Click 'Settings' → 'Connections'")
#         print("4. Ensure 'Allow External Connections' is enabled")
#         print("5. Add your IP address to the whitelist")
#         print("!" * 50)
#         sys.exit(1)
# Run this Python script to create a test table
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://personal_dashboard_g49i_user:lgo8xLgAXKk8BbvmYbasx8OlL0he14Vd@dpg-d58h5phr0fns73f8g570-a.oregon-postgres.render.com/personal_dashboard_g49i"

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS test_table (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP                                                                                            
        )
    """))

    conn.execute(text("""
        INSERT INTO test_table (name) 
        VALUES ('Test Record 1'), ('Test Record 2')
    """))

    conn.commit()
    print("✅ Test table created with sample data!")

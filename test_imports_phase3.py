"""FASE 3 — import-smoke-test voor de upload workflow."""
import sys
sys.path.insert(0, "/home/ubuntu/football_impact_platform")

ok = True
try:
    from physical_parser import parse_physical_file  # noqa: F401
    print("✓ physical_parser.parse_physical_file geïmporteerd")
except Exception as e:
    ok = False
    print(f"✗ physical_parser import faalde: {e}")

try:
    from database import (  # noqa: F401
        get_connection,
        save_physical_data,
        get_physical_data,
        list_physical_sessions,
        get_matches_for_date,
        physical_summary_counts,
    )
    print("✓ database-functies geïmporteerd")
except Exception as e:
    ok = False
    print(f"✗ database import faalde: {e}")

try:
    import pandas as pd  # noqa: F401
    print("✓ pandas geïmporteerd")
except Exception as e:
    ok = False
    print(f"✗ pandas import faalde: {e}")

print("\n✅ Alle imports OK" if ok else "\n❌ Imports onvolledig")
sys.exit(0 if ok else 1)

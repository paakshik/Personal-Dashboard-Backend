import pytest
from fastapi import HTTPException
from app.owner_access import is_server_owner, require_server_owner
try:
    from app.websockets.system_stream import require_server_owner_ws
except ImportError:
    require_server_owner_ws = None

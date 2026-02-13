"""Entry point for `python -m shopping_tool`."""
import asyncio
from .server import main

asyncio.run(main())

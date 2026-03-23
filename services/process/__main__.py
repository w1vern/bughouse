

import asyncio

from .main import serve

async def main() -> None:
    await asyncio.gather(serve())


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
from contextlib import suppress
from bot.config import settings

from bot.utils.launcher import process

REFER_LOCK = asyncio.Lock()

async def main():
    try:
        with open('refer.txt', 'r') as f:
            GLOBAL_REFER = {line.strip():0 for line in f.readlines()}
    except FileNotFoundError:
        GLOBAL_REFER = {settings.REF_ID:0}
        
    await process(GLOBAL_REFER, REFER_LOCK)



if __name__ == '__main__':
    with suppress(KeyboardInterrupt):
        asyncio.run(main())

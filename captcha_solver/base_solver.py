from __future__ import annotations

import random
from typing import Optional

from playwright.async_api import Page

from .capguru_client import CapGuruClient
from .helpers import sleep, rand

class CaptchaSolverBase:

    def __init__(
        self,
        page: Page,
        api_key: str,
        server: str = 'https://api.cap.guru',
        attempts: int = 5,
        debug: bool = False,
        selector: str = '',
    ) -> None:
        self.page = page
        self.api_key = api_key
        self.server = server
        self.attempts = attempts
        self.debug = debug
        self.selector = selector
        self.client = CapGuruClient(api_key, server)

    def _log(self, *args) -> None:
        if self.debug:
            print('[CaptchaSolver]', *args)

    async def _url_to_base64(self, url: str) -> str:
        return await self.page.evaluate("""async (imgUrl) => {
            const response = await fetch(imgUrl);
            const blob = await response.blob();
            return new Promise((resolve) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                reader.readAsDataURL(blob);
            });
        }""", url)

    async def _drag_slider(
        self,
        page: Page,
        from_x: float, from_y: float,
        to_x: float, to_y: float,
    ) -> None:
        await page.mouse.move(from_x, from_y)
        await sleep(rand(80, 180))
        await page.mouse.down()
        await sleep(rand(100, 300))

        steps = rand(25, 45)
        dist = to_x - from_x
        for i in range(1, steps + 1):
            p = i / steps
            ease = 2 * p * p if p < 0.5 else -1 + (4 - 2 * p) * p
            cur_x = from_x + dist * ease + random.uniform(-1.5, 1.5)
            cur_y = from_y + random.uniform(-2, 2)
            await page.mouse.move(cur_x, cur_y)
            await sleep(rand(8, 22))

        await page.mouse.move(to_x, from_y)
        await sleep(rand(80, 200))
        await page.mouse.up()

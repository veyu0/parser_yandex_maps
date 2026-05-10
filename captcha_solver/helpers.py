from __future__ import annotations

import asyncio
import base64
import random
import re
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Frame, Page, ElementHandle

async def sleep(ms: float) -> None:
    await asyncio.sleep(ms / 1000)

def rand(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)

@dataclass
class SelectorStep:
    type: str
    value: Optional[str] = None

def parse_selector(raw: str) -> list[SelectorStep]:
    steps: list[SelectorStep] = []
    parts = re.split(r'>(?=CSS>|XPATH>|FRAME>)', raw)
    for part in parts:
        trimmed = part.lstrip('>').strip()
        if not trimmed:
            continue
        if trimmed.startswith('CSS>'):
            steps.append(SelectorStep(type='css', value=trimmed[4:].strip()))
        elif trimmed.startswith('XPATH>'):
            steps.append(SelectorStep(type='xpath', value=trimmed[6:].strip()))
        elif trimmed.startswith('FRAME>'):
            steps.append(SelectorStep(type='frame'))
        else:
            steps.append(SelectorStep(type='css', value=trimmed))
    return steps

async def find_element(context: "Page | Frame", raw_selector: str) -> Optional[ElementHandle]:
    steps = parse_selector(raw_selector)
    ctx = context
    el: Optional[ElementHandle] = None
    for step in steps:
        if step.type == 'frame':
            if el is None:
                raise ValueError(f'FRAME step without prior element in: {raw_selector}')
            ctx = await el.content_frame()
            el = None
            continue
        if step.type == 'css':
            el = await ctx.query_selector(step.value)
        elif step.type == 'xpath':
            results = await ctx.query_selector_all(f'xpath={step.value}')
            el = results[0] if results else None
        if el is None:
            return None
    return el

async def wait_for_element(context: "Page | Frame", raw_selector: str, timeout: int = 15000) -> Optional[ElementHandle]:
    deadline = asyncio.get_event_loop().time() + timeout / 1000
    while asyncio.get_event_loop().time() < deadline:
        el = await find_element(context, raw_selector)
        if el:
            return el
        await sleep(300)
    return None

async def screenshot_element(el: ElementHandle) -> str:
    buf = await el.screenshot()
    return base64.b64encode(buf).decode()

async def canvas_to_base64(page: "Page | Frame", css_selector: str) -> Optional[str]:
    result = await page.evaluate(
        """(sel) => {
            const canvas = document.querySelector(sel);
            if (!canvas) return null;
            return canvas.toDataURL('image/png').split(',')[1];
        }""",
        css_selector,
    )
    return result

async def human_move(page: Page, x: float, y: float) -> None:
    await page.mouse.move(x, y, steps=rand(10, 25))

async def human_click(page: Page, x: float, y: float) -> None:
    await human_move(page, x, y)
    await sleep(rand(50, 150))
    await page.mouse.click(x, y, delay=rand(30, 80))

async def random_mouse_wiggle(page: Page) -> None:
    if random.random() > 0.5:
        return
    vp = page.viewport_size or {'width': 1280, 'height': 800}
    margin = 0.25
    x = rand(int(vp['width'] * margin), int(vp['width'] * (1 - margin)))
    y = rand(int(vp['height'] * margin), int(vp['height'] * (1 - margin)))
    await human_move(page, x, y)
    if random.random() > 0.5:
        await sleep(rand(100, 900))

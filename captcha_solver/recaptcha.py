from __future__ import annotations

import base64
import random
from typing import Optional

from playwright.async_api import Page

from .base_solver import CaptchaSolverBase
from .helpers import (
    sleep, rand, wait_for_element, screenshot_element, random_mouse_wiggle,
)

class RecaptchaSolver(CaptchaSolverBase):

    async def solve(self) -> bool:
        self._log('Solving reCAPTCHA v2...')
        await random_mouse_wiggle(self.page)
        for attempt in range(self.attempts):
            self._log(f'Attempt {attempt + 1}/{self.attempts}')
            try:
                if await self._attempt():
                    self._log('reCAPTCHA v2 solved!')
                    return True
            except Exception as e:
                self._log('Error in attempt:', e)
                if attempt < self.attempts - 1:
                    await sleep(rand(1000, 2000))
        raise RuntimeError('reCAPTCHA v2: failed after all attempts. Error: ERROR_CAPTCHA_UNSOLVABLE')

    async def _attempt(self) -> bool:
        page = self.page
        captured_payload_b64: list[str] = []

        async def _capture_payload(response):
            try:
                url = response.url
                if '/payload' in url and 'recaptcha' in url:
                    ct = response.headers.get('content-type', '')
                    if 'image' in ct or 'octet' in ct:
                        body = await response.body()
                        if body and len(body) > 1000:
                            captured_payload_b64.clear()
                            captured_payload_b64.append(base64.b64encode(body).decode())
            except Exception:
                pass

        page.on('response', _capture_payload)
        try:
            return await self._attempt_inner(page, captured_payload_b64)
        finally:
            page.remove_listener('response', _capture_payload)

    async def _attempt_inner(self, page: Page, captured_payload_b64: list) -> bool:
        checkbox_frame_el = await wait_for_element(page, '>CSS> iframe[src*="recaptcha"][src*="anchor"]', 10000)
        if not checkbox_frame_el:
            raise RuntimeError('reCAPTCHA iframe not found')
        checkbox_frame = await checkbox_frame_el.content_frame()
        checkbox = await checkbox_frame.query_selector('#recaptcha-anchor')
        if not checkbox:
            raise RuntimeError('reCAPTCHA checkbox not found')
        if not await checkbox_frame.query_selector('#recaptcha-anchor[aria-checked="true"]'):
            self._log('Clicking reCAPTCHA checkbox...')
            await sleep(rand(200, 600))
            await checkbox_frame.evaluate('el => el.click()', checkbox)
            await sleep(rand(1500, 3000))
        if await checkbox_frame.query_selector('#recaptcha-anchor[aria-checked="true"]'):
            self._log('reCAPTCHA solved without image challenge!')
            return True

        challenge_frame_el = await wait_for_element(page, '>CSS> iframe[src*="recaptcha"][src*="bframe"]', 10000)
        if not challenge_frame_el:
            raise RuntimeError('reCAPTCHA challenge iframe not found')
        cf = await challenge_frame_el.content_frame()

        for i in range(20):
            await sleep(rand(800, 1500))
            if await self._is_solved(cf, checkbox_frame):
                return True
            payload_el = await wait_for_element(cf, '>CSS> .rc-imageselect-payload', 8000)
            if not payload_el:
                raise RuntimeError('reCAPTCHA payload not found')
            await self._wait_stable(cf)

            is_44 = bool(await cf.query_selector('table.rc-imageselect-table-44'))
            is_33 = bool(await cf.query_selector('table.rc-imageselect-table-33'))
            if not is_33 and not is_44:
                await sleep(1000)
                is_44 = bool(await cf.query_selector('table.rc-imageselect-table-44'))
                is_33 = bool(await cf.query_selector('table.rc-imageselect-table-33'))

            sizex = 9 if is_33 else (16 if is_44 else 9)

            task_text = await cf.evaluate("""() => {
                const strong = document.querySelector('.rc-imageselect-instructions strong');
                if (strong) return strong.textContent.trim();
                const desc = document.querySelector('.rc-imageselect-desc-text');
                if (desc) return desc.textContent.trim();
                const el = document.querySelector('.rc-imageselect-instructions');
                if (!el) return '';
                return el.innerText.split('\\n')[0].trim();
            }""")
            if not task_text:
                await sleep(1000)
                continue

            image_b64 = captured_payload_b64[-1] if captured_payload_b64 else None
            if not image_b64:
                target_el = await cf.query_selector('#rc-imageselect-target')
                if target_el:
                    image_b64 = await screenshot_element(target_el)
            if not image_b64:
                continue

            result = await self.client.solve_recap(image_b64=image_b64, task_text=task_text, sizex=sizex, debug=self.debug)
            if not result or 'ERROR' in result or 'coordinates' in result:
                await self._reload(cf)
                await sleep(3000)
                continue
            if result in ('notpic', 'sorry'):
                await self._submit(cf)
                await sleep(rand(1000, 2000))
                continue

            tile_indices = self.client._parse_tile_indices(result)
            if not tile_indices:
                await self._reload(cf)
                continue

            random.shuffle(tile_indices)
            tile_info = await cf.evaluate("""() => {
                const tiles = document.querySelectorAll('.rc-imageselect-tile');
                if (tiles.length === 0) return null;
                const rect = tiles[0].getBoundingClientRect();
                return { x: rect.left, y: rect.top, w: rect.width, h: rect.height };
            }""")
            if not tile_info:
                continue

            for idx in tile_indices:
                await sleep(rand(200, 500))
                await cf.evaluate("""(args) => {
                    const tiles = document.querySelectorAll('.rc-imageselect-tile');
                    const tile = tiles[args.idx];
                    if (!tile) return;
                    const rect = tile.getBoundingClientRect();
                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    ['pointerenter','mouseenter','pointerover','mouseover',
                     'pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
                        tile.dispatchEvent(new MouseEvent(type, {
                            bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy
                        }));
                    });
                }""", {'idx': idx})
                if is_33:
                    await sleep(rand(300, 600))

            if is_33:
                await sleep(rand(1500, 2500))
                dynamic = await cf.query_selector('.rc-imageselect-dynamic-selected')
                if dynamic:
                    captured_payload_b64.clear()
                    for _ in range(10):
                        if not await cf.query_selector('.rc-imageselect-dynamic-selected'):
                            break
                        await sleep(1000)
                    continue

            await sleep(rand(500, 1000))
            await self._submit(cf)
            await sleep(rand(2500, 3500))
            if await self._is_solved(cf, checkbox_frame):
                return True

        raise RuntimeError('reCAPTCHA v2: could not solve after 20 iterations')

    async def _is_solved(self, cf, checkbox_frame) -> bool:
        try:
            if await checkbox_frame.query_selector('.recaptcha-checkbox[aria-checked="true"]'):
                return True
        except Exception:
            pass
        return await cf.evaluate("""() => {
            const submit = document.querySelector('#recaptcha-verify-button');
            const reload = document.querySelector('.rc-button-reload');
            if (submit && submit.disabled && reload && reload.classList.contains('rc-button-disabled')) return true;
            if (document.querySelectorAll('.rc-imageselect-correct, .rc-imageselect-success').length > 0) return true;
            return false;
        }""")

    async def _submit(self, cf) -> None:
        await cf.evaluate("""() => {
            const btn = document.querySelector('#recaptcha-verify-button');
            if (!btn) return;
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
                btn.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
            });
        }""")
        await sleep(rand(2500, 3500))

    async def _reload(self, cf) -> None:
        await cf.evaluate("""() => {
            const el = document.querySelector('.rc-button-reload');
            if (!el) return;
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
                el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
            });
        }""")
        await sleep(rand(1000, 1500))

    async def _wait_stable(self, cf) -> None:
        for _ in range(10):
            before = await cf.evaluate("() => document.querySelectorAll('.rc-imageselect-target img').length")
            await sleep(300)
            after = await cf.evaluate("() => document.querySelectorAll('.rc-imageselect-target img').length")
            dynamic = await cf.evaluate("() => document.querySelectorAll('.rc-imageselect-dynamic-selected').length")
            if before == after and before > 0 and dynamic == 0:
                return

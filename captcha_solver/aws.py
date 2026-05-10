from __future__ import annotations
import base64
import json
import re
from typing import Optional
from playwright.async_api import Page, Frame, Response
from .base_solver import CaptchaSolverBase
from .helpers import sleep, rand, human_click, canvas_to_base64

class AwsSolver(CaptchaSolverBase):
    CAPTCHA_SELECTORS = '#amzn-captcha-verify-button, .amzn-captcha-modal-title, .amzn-captcha-modal, [action$="validateCaptcha"]'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._problem_payload: Optional[dict] = None
        self._problem_handler_attached = False

    async def solve(self, wait_timeout: int=30000) -> bool:
        self._log('Solving AWS WAF...')
        self._attach_problem_listener()
        self._log(f'Waiting up to {wait_timeout}ms for captcha to load...')
        frame = await self._wait_for_captcha_frame(wait_timeout)
        if frame is None:
            raise RuntimeError('AWS: captcha area not found within timeout (bad proxy, page not ready, or no captcha on this page)')
        self._log('Captcha detected, starting solver loop')
        max_errors = max(self.attempts, 5)
        errors_in_a_row = 0
        rounds_solved = 0
        hard_cap = max(self.attempts * 5, 40)
        for iteration in range(hard_cap):
            self._log(f'Iter {iteration + 1} (solved: {rounds_solved}, errors: {errors_in_a_row})')
            frame = await self._find_captcha_frame()
            if frame is None:
                if iteration > 0:
                    self._log('Captcha gone — solved')
                    return True
                frame = await self._wait_for_captcha_frame(5000)
                if frame is None:
                    return True
            try:
                ok = await self._attempt(frame)
            except Exception as e:
                self._log('Attempt error:', e)
                errors_in_a_row += 1
                if errors_in_a_row >= max_errors:
                    raise RuntimeError(f'AWS: {errors_in_a_row} errors in a row, giving up')
                await self._refresh_captcha(frame)
                await sleep(rand(3000, 4500))
                continue
            if ok:
                self._log(f'AWS solved! Total rounds: {rounds_solved + 1}')
                return True
            rounds_solved += 1
            errors_in_a_row = 0
            self._log(f'Round {rounds_solved} accepted, next round...')
            await sleep(rand(1500, 3000))
        raise RuntimeError(f'AWS: hard cap {hard_cap} reached ({rounds_solved} rounds solved)')
        raise RuntimeError(f'AWS: failed to solve in {self.attempts} attempts')

    async def _find_captcha_frame(self) -> Optional[Frame]:
        page = self.page
        try:
            el = await page.query_selector(self.CAPTCHA_SELECTORS)
            if el and await el.is_visible():
                return page.main_frame
        except Exception:
            pass
        for fr in page.frames:
            try:
                el = await fr.query_selector(self.CAPTCHA_SELECTORS)
                if el and await el.is_visible():
                    return fr
            except Exception:
                continue
        return None

    async def _wait_for_captcha_frame(self, timeout_ms: int) -> Optional[Frame]:
        import time
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            frame = await self._find_captcha_frame()
            if frame is not None:
                return frame
            try:
                await self.page.wait_for_load_state('domcontentloaded', timeout=1000)
            except Exception:
                pass
            await sleep(500)
        return None

    def _attach_problem_listener(self) -> None:
        if self._problem_handler_attached:
            return

        async def _on_response(resp: Response) -> None:
            if 'problem' not in resp.url:
                return
            try:
                body = await resp.text()
            except Exception:
                return
            if 'problem_type' not in body:
                return
            try:
                data = json.loads(body)
            except Exception:
                return
            self._problem_payload = data
            self._log('Captured problem response:', data.get('problem_type'))
        self.page.on('response', lambda r: _on_response(r))
        self._problem_handler_attached = True

    async def _attempt(self, frame: Frame) -> bool:
        page = self.page
        for _ in range(30):
            alert = await frame.query_selector('div[role="alert"]')
            if not alert or not await alert.is_visible():
                break
            await sleep(3000)
        await sleep(1000)
        verify_btn = await frame.query_selector('#amzn-captcha-verify-button')
        if verify_btn and await verify_btn.is_visible():
            self._log('Clicking initial verify button')
            await verify_btn.click()
            await sleep(4000)
        self._problem_payload = None
        text_cap = ''
        type_cap = ''
        captcha_b64 = ''
        for _ in range(20):
            if self._problem_payload:
                break
            await sleep(500)
        if self._problem_payload:
            data = self._problem_payload
            text_cap = str(data.get('problem_type', ''))
            assets = data.get('assets', {}) or {}
            img_b64 = assets.get('image')
            if 'gridcaptcha' not in text_cap and img_b64:
                captcha_b64 = self._strip_data_url(img_b64)
            if text_cap == 'toycarcity':
                text_cap = 'Place a dot at the end of the cars path'
                type_cap = 'car'
            elif 'bifur' in text_cap:
                target = assets.get('target_name', '')
                text_cap = f'Slide the image to complete {target}'
                type_cap = 'slider'
                if img_b64:
                    captcha_b64 = self._strip_data_url(img_b64)
            elif 'gridcaptcha' in text_cap:
                text_cap = ''
            self._log('Problem payload type=' + (type_cap or '?') + ' text="' + text_cap + '"')
        text_form = await frame.query_selector('[action$="validateCaptcha"]')
        if text_form and (not text_cap):
            type_cap = 'text'
            text_cap = 'text'
        if not text_cap:
            canvas_grid = await frame.query_selector('#captcha-container form canvas')
            if canvas_grid:
                em = await frame.query_selector('#captcha-container form div em')
                if em:
                    obj = (await em.inner_text()).strip()
                    type_cap = 'grid'
                    text_cap = f'choose all {obj}'
        if text_cap and ('Incorrect' in text_cap or 'exceeded' in text_cap):
            text_cap = ''
        if not text_cap:
            self._log('Could not get task text')
            return False
        self._log(f'Task: "{text_cap}", type: {type_cap}')
        if type_cap == 'text':
            img = await frame.query_selector('form img')
            if img:
                png = await img.screenshot()
                captcha_b64 = base64.b64encode(png).decode('ascii')
        else:
            if not captcha_b64 or len(captcha_b64) < 5000:
                self._log('Trying canvas screenshot')
                canvas = await frame.query_selector('#captcha-container form canvas, form canvas')
                if canvas:
                    try:
                        png = await canvas.screenshot()
                        captcha_b64 = base64.b64encode(png).decode('ascii')
                    except Exception:
                        pass
            slider_img = await frame.query_selector('img[alt="Slider"]')
            if slider_img or 'Slide' in text_cap:
                type_cap = 'slider'
            if not captcha_b64 or len(captcha_b64) < 5000:
                self._log('Trying canvas.toDataURL()')
                try:
                    data_url = await frame.evaluate("() => {\n                            const c = document.querySelector(\n                                '#captcha-container form canvas, form canvas'\n                            );\n                            return c ? c.toDataURL() : '';\n                        }")
                    if data_url:
                        captcha_b64 = self._strip_data_url(data_url)
                except Exception:
                    pass
        if not captcha_b64 or len(captcha_b64) < 5000:
            self._log('Failed to obtain captcha image')
            return False
        result = await self.client.click({'method': 'base64', 'click': 'oth', 'textinstructions': f'Amazon,{text_cap}', 'body': captcha_b64}, debug=self.debug)
        if not result:
            self._log('Empty response from CapGuru')
            return False
        result = self._clean_result(result)
        self._log(f'CapGuru result: {result}')
        if type_cap == 'text':
            await self._apply_text(frame, result)
        elif type_cap == 'slider':
            await self._apply_slider(page, frame, result, captcha_b64)
        else:
            await self._apply_clicks(page, frame, result)
        verify_internal = await frame.query_selector('#amzn-btn-verify-internal')
        if verify_internal and await verify_internal.is_visible():
            self._log('Clicking verify-internal')
            prev_payload_id = id(self._problem_payload)
            self._problem_payload = None
            await verify_internal.click()
            await sleep(rand(1500, 2500))
            for _ in range(16):
                if self._problem_payload is not None:
                    self._log('New round detected — continuing')
                    return False
                still = await frame.query_selector(self.CAPTCHA_SELECTORS)
                if not still:
                    return True
                await sleep(500)
            _ = prev_payload_id
        for _ in range(30):
            alert = await frame.query_selector('div[role="alert"]')
            if alert and await alert.is_visible():
                await sleep(1000)
                continue
            again = await frame.query_selector('#amzn-btn-verify-internal+button')
            if not again:
                break
            style = await again.get_attribute('style') or ''
            if 'none' in style:
                break
            await sleep(1000)
        still = await frame.query_selector(self.CAPTCHA_SELECTORS)
        return not still

    async def _apply_text(self, frame: Frame, result: str) -> None:
        inp = await frame.query_selector('#captchacharacters')
        if not inp:
            raise RuntimeError('AWS text: input not found')
        await inp.click()
        await inp.fill('')
        await inp.type(result, delay=rand(30, 60))
        await sleep(rand(1000, 2000))
        btn = await frame.query_selector('[type="submit"]')
        if btn:
            await btn.click()
            await sleep(3000)

    async def _apply_clicks(self, page: Page, frame: Frame, result: str) -> None:
        canvas = await frame.query_selector('#captcha-container form canvas, form canvas')
        if not canvas:
            raise RuntimeError('AWS clicks: canvas not found')
        box = await canvas.bounding_box()
        if not box:
            raise RuntimeError('AWS clicks: canvas has no bbox')
        for pair in [p.strip() for p in result.split(';') if p.strip()]:
            parts = pair.split(',')
            if len(parts) < 2:
                continue
            try:
                x = int(re.sub('[^0-9-]', '', parts[0]))
                y = int(re.sub('[^0-9-]', '', parts[1]))
            except ValueError:
                continue
            await human_click(page, box['x'] + x, box['y'] + y)
            await sleep(rand(100, 500))

    async def _apply_slider(self, page: Page, frame: Frame, result: str, captcha_b64: str) -> None:
        first = result.split(',')[0]
        try:
            dx = int(re.sub('[^0-9-]', '', first))
        except ValueError:
            raise RuntimeError(f'AWS slider: bad result "{result}"')
        canvas = await frame.query_selector('#captcha-container form canvas, form canvas')
        if canvas:
            cw = await canvas.evaluate('el => el.width')
            if cw and cw != 324:
                dx = round(dx * 1.0 / 278 * (cw - 46))
        self._log(f'Slider dx: {dx}')
        slider = await frame.query_selector('img[alt="Slider"]')
        if not slider:
            raise RuntimeError('AWS slider: drag handle not found')
        box = await slider.bounding_box()
        if not box:
            raise RuntimeError('AWS slider: handle has no bbox')
        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        end_x = start_x + dx
        await page.mouse.move(start_x, start_y)
        await sleep(rand(150, 300))
        await page.mouse.down()
        await sleep(rand(100, 200))
        steps = max(20, abs(dx) // 5)
        for i in range(1, steps + 1):
            cx = start_x + (end_x - start_x) * (i / steps)
            await page.mouse.move(cx, start_y, steps=1)
            await sleep(rand(8, 22))
        await page.mouse.move(end_x, start_y)
        await sleep(rand(150, 300))
        await page.mouse.up()
        await sleep(3000)

    async def _refresh_captcha(self, frame: Frame) -> None:
        try:
            btn = await frame.query_selector('#amzn-btn-refresh-internal')
            if btn and await btn.is_visible():
                self._log('Refreshing captcha')
                await btn.click()
                self._problem_payload = None
        except Exception:
            pass

    @staticmethod
    def _strip_data_url(s: str) -> str:
        if not s:
            return ''
        if s.startswith('data:') and ',' in s:
            return s.split(',', 1)[1]
        return s

    @staticmethod
    def _clean_result(result: str) -> str:
        if not result:
            return ''
        if '|' in result:
            result = result.split('|', 1)[1]
        if 'coordinate:' in result:
            result = result.split('coordinate:', 1)[1]
        if 'coordinates:' in result:
            result = result.split('coordinates:', 1)[1]
        result = result.replace('x=', '').replace('y=', '')
        return result.strip()

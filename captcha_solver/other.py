from __future__ import annotations

import base64
import re
from typing import Optional

from playwright.async_api import Page

from .base_solver import CaptchaSolverBase
from .helpers import (
    sleep, rand, wait_for_element, screenshot_element, canvas_to_base64,
    human_click, random_mouse_wiggle,
)

class OtherSolver(CaptchaSolverBase):

    async def solve(self, selector: str = '') -> bool:
        self._log('Solving Other...')
        await random_mouse_wiggle(self.page)
        sel = selector or self.selector
        max_iterations = self.attempts + 3
        errors = 0
        for _ in range(max_iterations):
            try:
                result = await self._attempt(sel)
                if result is True:
                    self._log('Other solved!')
                    return True
                elif result is False:
                    await sleep(rand(1000, 2000))
                    continue
            except Exception as e:
                self._log('Error:', e)
                errors += 1
                if errors >= self.attempts:
                    break
                await sleep(rand(1500, 3000))
        raise RuntimeError('Other: failed.')

    async def _attempt(self, sel: str) -> bool:
        page = self.page
        captcha_frame = page

        if sel:
            iframe_el = await wait_for_element(page, sel, 10000)
            if iframe_el:
                captcha_frame = await iframe_el.content_frame() or page
        else:
            auto_el = await wait_for_element(
                page,
                '>CSS> iframe[src*="smartcaptcha"], iframe[src*="captcha-api"]',
                8000,
            )
            if auto_el:
                captcha_frame = await auto_el.content_frame() or page

        checkbox = await captcha_frame.query_selector('.CheckboxCaptcha-Anchor')
        slider = await captcha_frame.query_selector('.CaptchaSlider')

        if checkbox and await self._is_visible(captcha_frame, '.CheckboxCaptcha-Anchor'):
            class_name = await checkbox.get_attribute('class') or ''
            if 'pending' not in class_name:
                self._log('Phase 1: clicking checkbox')
                await sleep(rand(800, 1500))
                inp = await captcha_frame.query_selector('.CheckboxCaptcha-Anchor input')
                if inp:
                    cx, cy = await self._center_of(inp)
                    await human_click(page, cx, cy)
                else:
                    cx, cy = await self._center_of(checkbox)
                    await human_click(page, cx, cy)
            else:
                self._log('Phase 1: checkbox already pending')

            self._log('Checkbox clicked, waiting for captcha to load...')
            await sleep(rand(3000, 5000))
            return False

        elif slider and await self._is_visible(captcha_frame, '.CaptchaSlider'):
            advanced_already = await self._detect_advanced(captcha_frame)
            if advanced_already:
                self._log(f'Phase 1: slider visible but advanced captcha already present ({advanced_already}), skipping drag')
            else:
                self._log('Phase 1: dragging slider')
                await sleep(rand(600, 1200))
                thumb = await captcha_frame.query_selector('.CaptchaSlider .Thumb')
                if thumb:
                    slider_box = await slider.bounding_box()
                    if slider_box:
                        await self._drag_element(page, thumb, slider_box['width'])
                await sleep(rand(2000, 3500))

        try:
            detected = await self._detect_advanced(captcha_frame)
        except Exception as e:
            if 'context was destroyed' in str(e).lower() or 'navigation' in str(e).lower() \
                    or 'detached' in str(e).lower():
                self._log('Page navigated — captcha solved')
                return True
            raise

        if detected == 'figur':
            self._log('Detected: figur (AdvancedCaptcha-ImageWrapper)')
            return await self._solve_two_images_v2(page, captcha_frame)
        elif detected == 'kaleidoscope':
            self._log('Detected: kaleidoscope')
            return await self._solve_kaleidoscope(page, captcha_frame)
        elif detected == 'text':
            self._log('Detected: text captcha')
            return await self._solve_text_input(page, captcha_frame)
        elif detected == 'image_click':
            self._log('Detected: image click (legacy)')
            return await self._solve_image_click(page, captcha_frame)
        elif detected == 'two_images':
            self._log('Detected: two-image click (legacy)')
            return await self._solve_two_images(page, captcha_frame)
        elif detected == 'kaleidoscope_canvas':
            self._log('Detected: kaleidoscope canvas (legacy)')
            return await self._solve_kaleidoscope(page, captcha_frame)

        try:
            await sleep(rand(1000, 2000))
            still_visible = False
            for sel_check in [
                '.CheckboxCaptcha-Anchor',
                '.CaptchaSlider',
                '.AdvancedCaptcha-ImageWrapper',
                '.AdvancedCaptcha_kaleidoscope',
                '.AdvancedCaptcha-View>img',
            ]:
                el = await captcha_frame.query_selector(sel_check)
                if el and await self._is_visible(captcha_frame, sel_check):
                    still_visible = True
                    break
        except Exception as e:
            if 'context was destroyed' in str(e).lower() or 'navigation' in str(e).lower() \
                    or 'detached' in str(e).lower():
                self._log('Page navigated — captcha solved')
                return True
            raise

        if not still_visible:
            self._log('No captcha elements visible — likely solved')
            return True

        raise RuntimeError('Other: unknown captcha type')

    async def _detect_advanced(self, captcha_frame) -> str | None:
        """Detect which advanced captcha type is currently visible."""
        if await captcha_frame.query_selector('.AdvancedCaptcha-ImageWrapper') \
                and await self._is_visible(captcha_frame, '.AdvancedCaptcha-ImageWrapper'):
            return 'figur'
        if await captcha_frame.query_selector('.AdvancedCaptcha_kaleidoscope') \
                and await self._is_visible(captcha_frame, '.AdvancedCaptcha_kaleidoscope'):
            return 'kaleidoscope'
        if await captcha_frame.query_selector('.AdvancedCaptcha-View>img') \
                and await self._is_visible(captcha_frame, '.AdvancedCaptcha-View>img'):
            return 'text'
        if await captcha_frame.query_selector('img[src*="/captchaimage"], img[src*="/captchaimg"]'):
            return 'image_click'
        if await captcha_frame.query_selector('img[src*="data=img"]') \
                and await captcha_frame.query_selector('img[src*="data=task"]'):
            return 'two_images'
        if await captcha_frame.query_selector('canvas.AdvancedCaptcha-KaleidoscopeCanvas'):
            return 'kaleidoscope_canvas'
        return None

    async def _fetch_image_b64(self, page_or_frame, url: str) -> str:
        """
        Fetch an image URL and return its base64 content.
        Tries multiple strategies:
          1. Playwright page.evaluate with same-origin fetch (+ credentials)
          2. Draw an existing <img> element to an offscreen canvas
          3. Playwright APIRequestContext (server-side, no CORS)
          4. Fall back to self._url_to_base64 (base class method)
        """
        if not url:
            return ''

        try:
            b64 = await page_or_frame.evaluate(
                '''async (url) => {
                    try {
                        const r = await fetch(url, { credentials: "include" });
                        if (!r.ok) return null;
                        const blob = await r.blob();
                        return await new Promise((res, rej) => {
                            const reader = new FileReader();
                            reader.onloadend = () => res(reader.result.split(",")[1]);
                            reader.onerror = rej;
                            reader.readAsDataURL(blob);
                        });
                    } catch { return null; }
                }''',
                url,
            )
            if b64:
                return b64
        except Exception:
            pass

        try:
            b64 = await page_or_frame.evaluate(
                '''(url) => {
                    try {
                        const imgs = document.querySelectorAll("img");
                        for (const img of imgs) {
                            if (img.src === url || img.src.includes(url)) {
                                const c = document.createElement("canvas");
                                c.width = img.naturalWidth || img.width;
                                c.height = img.naturalHeight || img.height;
                                c.getContext("2d").drawImage(img, 0, 0);
                                return c.toDataURL("image/png").split(",")[1];
                            }
                        }
                    } catch {}
                    return null;
                }''',
                url,
            )
            if b64:
                return b64
        except Exception:
            pass

        try:
            page = self.page
            context = page.context
            api = context.request
            resp = await api.get(url)
            if resp.ok:
                body_bytes = await resp.body()
                return base64.b64encode(body_bytes).decode('ascii')
        except Exception:
            pass

        try:
            result = await self._url_to_base64(url)
            if isinstance(result, list):
                return result[0] if result else ''
            return result or ''
        except Exception:
            return ''

    @staticmethod
    def _build_task_url(url: str) -> str:
        """Convert a data=img URL to data=task (mirrors buildOtherTaskUrl in ya.js)."""
        if not url:
            return ''
        if re.search(r'[?&]b?data=task\b', url, re.IGNORECASE):
            return url
        m = re.search(r'([?&])(b?data)=img\b', url, re.IGNORECASE)
        if m:
            return url[:m.start()] + m.group(1) + m.group(2) + '=task' + url[m.end():]
        sep = '&' if '?' in url else '?'
        return url + sep + 'data=task'

    async def _is_visible(self, frame, selector: str) -> bool:
        try:
            return await frame.eval_on_selector(
                selector,
                '''el => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                        && s.visibility !== 'hidden'
                        && s.display !== 'none';
                }''',
            )
        except Exception:
            return False

    async def _center_of(self, element):
        box = await element.bounding_box()
        if not box:
            return None
        return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2

    async def _drag_element(self, page: Page, element, track_width: float):
        """
        Drag a slider thumb to the end of its track.
        Mirrors humanDrag() from the Chrome extension ya.js.
        Uses Playwright mouse API with human-like movement.
        """
        try:
            await page.mouse.up()
        except Exception:
            pass
        await sleep(rand(100, 200))

        thumb_box = await element.bounding_box()
        if not thumb_box:
            return

        try:
            slider_handle = await element.evaluate_handle('el => el.closest(".CaptchaSlider")')
            slider_box = await slider_handle.bounding_box() if slider_handle else None
        except Exception:
            slider_box = None

        start_x = thumb_box['x'] + thumb_box['width'] / 2
        start_y = thumb_box['y'] + thumb_box['height'] / 2

        if slider_box:
            track_end = slider_box['x'] + slider_box['width'] - thumb_box['width'] / 2
            distance = track_end - start_x
        else:
            distance = track_width

        if distance <= 5:
            return

        target_x = start_x + distance

        await page.mouse.move(start_x, start_y)
        await sleep(rand(150, 400))

        await page.mouse.down()
        await sleep(rand(50, 150))

        import random as _rnd
        steps = max(20, int(distance / 2.5) + _rnd.randint(15, 35))
        y_drift = 0.0
        y_drift_dir = 1 if _rnd.random() < 0.5 else -1

        for i in range(steps + 1):
            progress = i / steps

            if progress < 0.5:
                eased = 4 * progress * progress * progress
            else:
                eased = 1 - pow(-2 * progress + 2, 3) / 2

            current_x = start_x + distance * eased

            y_drift += _rnd.gauss(0, 0.4) * y_drift_dir
            y_drift *= 0.90
            current_y = start_y + y_drift + _rnd.gauss(0, 1.2)

            await page.mouse.move(current_x, current_y, steps=1)

            import math
            speed_curve = math.sin(progress * math.pi)
            base_wait = 16 / (0.8 + speed_curve * 0.4)

            extra_wait = 0
            if _rnd.random() < 0.04:
                extra_wait = _rnd.gauss(50, 18)

            wait_ms = max(6, base_wait + _rnd.gauss(0, 3) + extra_wait)
            await sleep(int(wait_ms))

        await sleep(rand(80, 250))
        await page.mouse.up()

    async def _solve_image_click(self, page: Page, frame) -> bool:
        main_img = await frame.query_selector(
            'img[src*="/captchaimage"], img[src*="/captchaimg"]'
        )
        img_src = await main_img.evaluate('el => el.src')
        b64 = (
            await self._fetch_image_b64(frame, img_src)
            if img_src.startswith('http')
            else await screenshot_element(main_img)
        )
        result = await self.client.click(
            {'type': 'base64', 'vernet': '18', 'body': b64}, debug=self.debug
        )
        if not result:
            raise RuntimeError('Other type 1: no result')

        img_dims = await main_img.evaluate(
            '''el => ({
                natW: el.naturalWidth || el.width,
                natH: el.naturalHeight || el.height,
                cssW: el.clientWidth || el.offsetWidth,
                cssH: el.clientHeight || el.offsetHeight
            })'''
        )
        coord_str = result.split('coordinates:')[1] if 'coordinates:' in result else result
        img_box = await main_img.bounding_box()

        for pair in [c.strip() for c in coord_str.split(';') if c.strip()]:
            x_val = int(re.sub(r'[^0-9]', '', pair.split(',')[0].split('=')[1]))
            y_val = int(re.sub(r'[^0-9]', '', pair.split(',')[1].split('=')[1]))
            await human_click(
                page,
                img_box['x'] + x_val / (img_dims['natW'] or 300) * (img_dims['cssW'] or 300),
                img_box['y'] + y_val / (img_dims['natH'] or 200) * (img_dims['cssH'] or 200),
            )

        await sleep(rand(500, 1000))
        btn = await frame.query_selector('button[type="submit"]')
        if btn:
            await btn.click(delay=rand(30, 80))
        await sleep(rand(1500, 2500))
        return not await frame.query_selector(
            'img[src*="/captchaimage"], img[src*="/captchaimg"]'
        )

    async def _solve_two_images(self, page: Page, frame) -> bool:
        data_img_el = await frame.query_selector('img[src*="data=img"]')
        data_task_el = await frame.query_selector('img[src*="data=task"]')
        body0 = await self._fetch_image_b64(frame, await data_img_el.evaluate('el => el.src'))
        body1 = await self._fetch_image_b64(frame, await data_task_el.evaluate('el => el.src'))
        raw_result = await self.client.click({
            'type': 'base64',
            'body0': body0,
            'body1': body1,
            'click': 'oth',
            'textinstructions': 'other',
        }, debug=self.debug)
        coord_str = (
            raw_result.split('coordinates:')[1]
            if 'coordinates:' in raw_result
            else raw_result
        )
        img_box = await data_img_el.bounding_box()
        img_dims = await data_img_el.evaluate(
            '''el => ({
                natW: el.naturalWidth || el.width,
                natH: el.naturalHeight || el.height,
                cssW: el.clientWidth || el.offsetWidth,
                cssH: el.clientHeight || el.offsetHeight
            })'''
        )

        for pair in [c.strip() for c in coord_str.split(';') if c.strip()]:
            x_val = int(re.sub(r'[^0-9]', '', pair.split(',')[0].split('=')[1]))
            y_val = int(re.sub(r'[^0-9]', '', pair.split(',')[1].split('=')[1]))
            await human_click(
                page,
                img_box['x'] + x_val / (img_dims['natW'] or 300) * (img_dims['cssW'] or 300),
                img_box['y'] + y_val / (img_dims['natH'] or 200) * (img_dims['cssH'] or 200),
            )

        await sleep(rand(500, 1000))
        btn = await frame.query_selector('button[type="submit"]')
        if btn:
            await btn.click(delay=rand(30, 80))
        await sleep(rand(1500, 2500))
        return not await frame.query_selector('img[src*="data=img"]')

    async def _solve_two_images_v2(self, page: Page, frame) -> bool:
        """
        Mirrors the Chrome extension's `form3` branch.
        Gets the main image and builds the task URL from it.
        """
        img_el = await frame.query_selector('.AdvancedCaptcha-ImageWrapper img')
        if not img_el:
            raise RuntimeError('Other figur: .AdvancedCaptcha-ImageWrapper img not found')

        img_src = await img_el.evaluate('el => el.src')
        body0 = await self._fetch_image_b64(frame, img_src)

        task_url = self._build_task_url(img_src)
        body1 = ''
        if task_url:
            try:
                body1 = await self._fetch_image_b64(frame, task_url)
            except Exception:
                pass

        if not body1:
            try:
                body1 = await canvas_to_base64(frame, '.AdvancedCaptcha-View canvas')
            except Exception:
                pass

        if not body0 or not body1:
            raise RuntimeError('Other figur: failed to extract images')

        raw_result = await self.client.click({
            'type': 'base64',
            'body0': body0,
            'body1': body1,
            'click': 'oth',
            'textinstructions': 'other',
        }, debug=self.debug)

        coord_str = (
            raw_result.split('coordinates:')[1]
            if 'coordinates:' in raw_result
            else raw_result
        )
        coord_str = re.sub(r'[^0-9,;]', '', coord_str)

        wrapper = await frame.query_selector('.AdvancedCaptcha-ImageWrapper')
        wrapper_box = await wrapper.bounding_box()

        for pair in [c.strip() for c in coord_str.split(';') if c.strip()]:
            parts = pair.split(',')
            if len(parts) >= 2:
                x_val = int(parts[0])
                y_val = int(parts[1])
                await sleep(rand(200, 600))
                await human_click(
                    page,
                    wrapper_box['x'] + x_val,
                    wrapper_box['y'] + y_val,
                )

        await sleep(rand(1500, 2500))
        btn = await frame.query_selector('button[data-testid="submit"]')
        if not btn:
            btn = await frame.query_selector('button[type="submit"]')
        if btn:
            await btn.click(delay=rand(30, 80))
        await sleep(rand(2500, 3500))
        return not await frame.query_selector('.AdvancedCaptcha-ImageWrapper')

    async def _solve_kaleidoscope(self, page: Page, frame) -> bool:
        """
        Mirrors the Chrome extension's `form4` (puzzle) branch.
        Extracts the puzzle task array and image, then drags the slider
        to the value returned by the API.
        """
        puzzle = ''
        img_src = ''

        try:
            ssr = await frame.evaluate(
                '''() => {
                    if (window.__SSR_DATA__ && window.__SSR_DATA__.imageSrc && window.__SSR_DATA__.task) {
                        return {
                            imageSrc: window.__SSR_DATA__.imageSrc,
                            task: Array.isArray(window.__SSR_DATA__.task)
                                ? window.__SSR_DATA__.task.join(",")
                                : String(window.__SSR_DATA__.task)
                        };
                    }
                    return null;
                }'''
            )
            if ssr:
                img_src = ssr['imageSrc']
                puzzle = ssr['task']
        except Exception:
            pass

        if not puzzle or not img_src:
            body_html = await frame.evaluate('() => document.body ? document.body.innerHTML : ""')
            task_match = re.search(r'"task"\s*:\s*\[([^\]]+)\]', body_html) or re.search(
                r'\[([0-9,\s]+)\]', body_html
            )
            img_match = re.search(r'"imageSrc"\s*:\s*"(.*?)"', body_html) or re.search(
                r',imageSrc:"(.*?)"', body_html
            )
            if task_match and img_match:
                puzzle = re.sub(r'[^0-9,]', '', task_match.group(1))
                img_src = img_match.group(1)
            else:
                canvas_sel = 'canvas.AdvancedCaptcha-KaleidoscopeCanvas'
                canvas_el = await frame.query_selector(canvas_sel)
                if not canvas_el:
                    canvas_el = await frame.query_selector('.AdvancedCaptcha-View canvas')
                if canvas_el:
                    b64 = await canvas_to_base64(frame, canvas_sel)
                    task_text = ''
                    try:
                        task_text = await frame.eval_on_selector(
                            '.AdvancedCaptcha-Task', 'el => el.textContent.trim()'
                        )
                    except Exception:
                        pass
                    raw_result = await self.client.click({
                        'type': 'base64',
                        'body': b64,
                        'click': 'oth2',
                        'textinstructions': task_text,
                    }, debug=self.debug)
                    coord_str = (
                        raw_result.split('coordinates:')[1]
                        if 'coordinates:' in raw_result
                        else raw_result
                    )
                    box = await canvas_el.bounding_box()
                    canvas_dims = await frame.evaluate(
                        '''(sel) => {
                            const c = document.querySelector(sel);
                            return {w: c.width, h: c.height, cssW: c.clientWidth, cssH: c.clientHeight};
                        }''',
                        canvas_sel,
                    )
                    for pair in [c.strip() for c in coord_str.split(';') if c.strip()]:
                        x_val = int(re.sub(r'[^0-9]', '', pair.split(',')[0].split('=')[1]))
                        y_val = int(re.sub(r'[^0-9]', '', pair.split(',')[1].split('=')[1]))
                        await human_click(
                            page,
                            box['x'] + x_val / canvas_dims['w'] * canvas_dims['cssW'],
                            box['y'] + y_val / canvas_dims['h'] * canvas_dims['cssH'],
                        )
                    await sleep(rand(600, 1000))
                    btn = await frame.query_selector('button[type="submit"]')
                    if btn:
                        await btn.click(delay=rand(30, 80))
                    await sleep(rand(1500, 2500))
                    return not await frame.query_selector(canvas_sel)
                raise RuntimeError('Other kaleidoscope: could not extract puzzle data')

        b64 = await self._fetch_image_b64(frame, img_src)
        if isinstance(b64, list):
            b64 = b64[0] if b64 else ''
        raw_result = await self.client.click({
            'type': 'base64',
            'body': b64,
            'click': 'oth2',
            'textinstructions': 'puzzlekal-' + (puzzle if isinstance(puzzle, str) else ''),
        }, debug=self.debug)

        slider_value = int(re.sub(r'[^0-9]', '', str(raw_result)))
        self._log(f'Puzzle answer: {slider_value}')

        slider_el = await frame.query_selector('.CaptchaSlider')
        thumb_el = await frame.query_selector('.CaptchaSlider .Thumb')
        if not slider_el or not thumb_el:
            raise RuntimeError('Other puzzle: slider/thumb not found')

        thumb_box = await thumb_el.bounding_box()
        slider_box = await slider_el.bounding_box()
        if thumb_box and slider_box:
            thumb_offset = thumb_box['x'] - slider_box['x']
            if thumb_offset > thumb_box['width']:
                self._log('Resetting slider to start position')
                await self._drag_slider_to_start(page, thumb_el, slider_box)
                await sleep(rand(300, 600))
                slider_el = await frame.query_selector('.CaptchaSlider')
                thumb_el = await frame.query_selector('.CaptchaSlider .Thumb')
                if not slider_el or not thumb_el:
                    raise RuntimeError('Other puzzle: slider/thumb not found after reset')
                slider_box = await slider_el.bounding_box()

        await self._drag_slider_to_value(page, frame, thumb_el, slider_value, slider_box['width'])

        await sleep(rand(800, 1800))

        btn = await frame.query_selector('button[data-testid="submit"]')
        if not btn:
            btn = await frame.query_selector('button[type="submit"]')
        if btn:
            self._log('Clicking submit')
            btn_box = await btn.bounding_box()
            if btn_box:
                await page.mouse.move(
                    btn_box['x'] + btn_box['width'] / 2 + rand(-5, 5),
                    btn_box['y'] + btn_box['height'] / 2 + rand(-3, 3),
                )
                await sleep(rand(150, 400))
            await btn.click(delay=rand(40, 100))
        else:
            self._log('WARNING: submit button not found!')

        await sleep(rand(2500, 4000))
        return not await frame.query_selector('.AdvancedCaptcha_kaleidoscope')

    async def _solve_text_input(self, page: Page, frame) -> bool:
        """Mirrors the Chrome extension's `form5` (text) branch."""
        img_el = await frame.query_selector('.AdvancedCaptcha-View>img')
        if not img_el:
            raise RuntimeError('Other text: image element not found')

        img_src = await img_el.evaluate('el => el.src')
        b64 = await self._fetch_image_b64(frame, img_src)
        if isinstance(b64, list):
            b64 = b64[0] if b64 else ''

        raw_result = await self.client.click({
            'type': 'base64',
            'body': b64,
            'vernet': '18',
        }, debug=self.debug)

        if not raw_result:
            raise RuntimeError('Other text: no result from API')

        text_input = await frame.query_selector('.Textinput-Control')
        if not text_input:
            text_input = await frame.query_selector('input[type="text"]')
        if not text_input:
            raise RuntimeError('Other text: input field not found')

        await text_input.click()
        await sleep(rand(200, 500))
        await text_input.fill('')
        await sleep(rand(100, 300))
        await text_input.type(str(raw_result), delay=rand(50, 120))

        await sleep(rand(1500, 2500))
        await text_input.press('Enter')
        await sleep(rand(2500, 3500))

        return not await frame.query_selector('.AdvancedCaptcha-View>img')

    async def _drag_slider_to_start(self, page: Page, thumb, slider_box: dict):
        """Drag the slider thumb back to the start (left edge) of the track."""
        import random as _rnd

        try:
            await page.mouse.up()
        except Exception:
            pass
        await sleep(rand(100, 200))

        thumb_box = await thumb.bounding_box()
        if not thumb_box:
            return

        start_x = thumb_box['x'] + thumb_box['width'] / 2
        start_y = thumb_box['y'] + thumb_box['height'] / 2
        target_x = slider_box['x'] + thumb_box['width'] / 2 + 2
        distance = start_x - target_x

        if distance <= 2:
            return

        await page.mouse.move(start_x, start_y)
        await sleep(rand(150, 350))
        await page.mouse.down()
        await sleep(rand(50, 150))

        steps = max(15, int(distance / 3) + _rnd.randint(10, 20))
        for i in range(steps + 1):
            progress = i / steps
            if progress < 0.5:
                eased = 4 * progress * progress * progress
            else:
                eased = 1 - pow(-2 * progress + 2, 3) / 2
            cx = start_x - distance * eased
            cy = start_y + _rnd.gauss(0, 1.0)
            await page.mouse.move(cx, cy, steps=1)
            await sleep(rand(8, 22))

        await sleep(rand(80, 200))
        await page.mouse.up()
        await sleep(rand(200, 500))

    async def _drag_slider_to_value(
        self, page: Page, frame, thumb, target_value: int, max_width: float
    ):
        """
        Mirrors humanDragToValue from ya.js.
        Drags the slider thumb step by step, reading aria-valuenow,
        until it reaches the target value. Uses human-like variable speed.
        """
        import random as _rnd
        import math

        box = await thumb.bounding_box()
        if not box:
            return

        try:
            await page.mouse.up()
        except Exception:
            pass
        await sleep(rand(100, 200))

        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2

        await page.mouse.move(start_x, start_y)
        await sleep(rand(200, 500))
        await page.mouse.down()
        await sleep(rand(80, 200))

        aria_max = int(await thumb.get_attribute('aria-valuemax') or '100')
        aria_min = int(await thumb.get_attribute('aria-valuemin') or '0')

        target_aria = target_value
        if target_aria > aria_max + 2:
            slider_el = await frame.query_selector('.CaptchaSlider')
            slider_rect = await slider_el.bounding_box() if slider_el else None
            track_width = (slider_rect['width'] if slider_rect else max_width)
            max_distance = max(1, track_width - box['width'])
            target_aria = round((target_value / max_distance) * (aria_max - aria_min) + aria_min)
        target_aria = max(aria_min, min(aria_max, target_aria))

        step_px = 4
        current_offset = 0
        last_aria = None
        last_pause_offset = 0
        y_drift = 0.0
        y_drift_dir = 1 if _rnd.random() < 0.5 else -1

        max_steps = int(max_width / step_px) + 60
        for step_i in range(max_steps):
            current_offset += step_px + _rnd.gauss(0, 0.8)
            cx = start_x + current_offset

            y_drift += _rnd.gauss(0, 0.4) * y_drift_dir
            y_drift *= 0.90
            cy = start_y + y_drift + _rnd.gauss(0, 1.2)

            await page.mouse.move(cx, cy, steps=1)

            now_raw = await thumb.get_attribute('aria-valuenow')
            now_val = None
            if now_raw is not None:
                now_val = int(now_raw)
                last_aria = now_val

                if now_val >= target_aria:
                    if now_val > target_aria:
                        for _back in range(30):
                            current_offset -= 1
                            bx = start_x + current_offset
                            by = start_y + _rnd.gauss(0, 0.8)
                            await page.mouse.move(bx, by, steps=1)
                            await sleep(rand(45, 80))
                            bk_raw = await thumb.get_attribute('aria-valuenow')
                            if bk_raw is not None and int(bk_raw) <= target_aria:
                                break
                    break

            progress_to_target = 0.0
            if aria_max > aria_min and target_aria > aria_min and last_aria is not None:
                progress_to_target = min(1.0, max(0.0,
                    (last_aria - aria_min) / (target_aria - aria_min)))

            speed_ms = (
                45
                + int((1 - math.sin(progress_to_target * math.pi * 0.5)) * 90)
                + _rnd.randint(0, 55)
            )
            if _rnd.random() < 0.06:
                speed_ms += int(abs(_rnd.gauss(85, 28)))

            await sleep(speed_ms)

            if _rnd.random() < 0.035 and (current_offset - last_pause_offset) > 50:
                await sleep(rand(30, 80))
                last_pause_offset = current_offset

        if last_aria is None:
            fallback_dist = (target_aria / max(1, aria_max - aria_min)) * max_width
            target_x = start_x + max(0, min(max_width, fallback_dist))
            await page.mouse.move(target_x, start_y, steps=1)
            await sleep(rand(30, 60))

        await sleep(rand(100, 350))
        await page.mouse.up()
        await sleep(rand(400, 800))

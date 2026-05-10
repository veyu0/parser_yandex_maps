from __future__ import annotations

import random
import re

from playwright.async_api import Page

from .base_solver import CaptchaSolverBase
from .helpers import (
    sleep, rand, wait_for_element, screenshot_element, human_click, random_mouse_wiggle,
)

class GeetestSolver(CaptchaSolverBase):

    async def solve(self, selector: str = '') -> bool:
        self._log('Solving GeeTest...')
        await random_mouse_wiggle(self.page)
        for _ in range(30):
            el = await self.page.query_selector(
                "[class*='geetest_btn_click'], [class*='geetest_radar_btn'], "
                "[class*='geetest_holder'], [class*='geetest_box_wrap']"
            )
            if el:
                await sleep(rand(300, 600))
                break
            await sleep(300)
        for attempt in range(self.attempts):
            self._log(f'Attempt {attempt + 1}/{self.attempts}')
            try:
                if await self._attempt():
                    self._log('GeeTest solved!')
                    return True
            except Exception as e:
                self._log('Error:', e)
                if attempt < self.attempts - 1:
                    await sleep(rand(1500, 3000))
        raise RuntimeError('GeeTest: failed. Error: ERROR_CAPTCHA_UNSOLVABLE')

    async def _detect_type(self, page: Page) -> str:
        if await page.query_selector("div[class*='geetest_holder'][class*='geetest_ant'] :first-child[class*='geetest_canvas_img'] :first-child[class*='geetest_slicebg']"):
            return 'GEETEST_VERSION_3_SLIDER'
        if await page.query_selector("div[class*='geetest_silver'][style*='block'] [class*='geetest_item_wrap']"):
            return 'GEETEST_VERSION_3_CLICK'
        if await page.query_selector("div[class*='geetest_box'][style*='block'] :first-child[class*='geetest_track']"):
            return 'GEETEST_VERSION_4_SLIDER'
        if await page.query_selector("[class*='geetest_box'][style*='block'] :first-child[class*='geetest_item-0-0']"):
            return 'GEETEST_VERSION_4_SWAP_ITEMS'
        v4_click = await page.evaluate("""() => {
            const el = document.querySelector("[class*='geetest_box_wrap'][style*='block'] :first-child[class*='geetest_box']");
            if (!el) return false;
            const wrap = el.closest("[class*='geetest_box_wrap']");
            if (!wrap) return false;
            if (wrap.querySelector("[class*='geetest_track']")) return false;
            if (wrap.querySelector("[class*='geetest_item-0-0']")) return false;
            return true;
        }""")
        if v4_click:
            return 'GEETEST_VERSION_4_CLICK'
        v3_radar = await page.query_selector(
            "[class*='geetest_radar_btn'], [class*='geetest_radar_tip'], "
            "[class*='geetest_holder']:not([style*='none'])"
        )
        if v3_radar:
            return 'GEETEST_CHECKBOX_V3'
        v4_box = await page.query_selector(
            "[class*='geetest_btn_click'], "
            "[class*='geetest_box_wrap']:not([style*='none']), "
            "[class*='geetest_checkbox']:not([style*='none'])"
        )
        if v4_box:
            return 'GEETEST_CHECKBOX_V4'
        return 'UNKNOWN'

    _CHECKBOX_SELECTORS = [
        ".geetest_radar_btn",
        "[class*='geetest_radar_btn']",
        ".geetest_btn",
        "[class*='geetest_checkbox']",
        "[class*='geetest_btn_click']",
        "[class*='geetest_box'] [class*='geetest_btn']",
        "[class*='geetest_holder'] [class*='geetest_icon']",
        "[class*='geetest_radar_tip']",
        "[class*='geetest_radar']",
    ]

    async def _click_checkbox(self, page) -> bool:
        """Try to click the GeeTest checkbox / radar button to open the captcha window."""
        sel = self.selector
        if sel:
            self._log('GeeTest: trying user selector:', sel)
            css = re.sub(r'^(>?CSS>\s*)+', '', sel).strip()
            btn = await page.query_selector(css) if css else None
            if btn:
                await btn.scroll_into_view_if_needed()
                await sleep(rand(200, 500))
                await btn.click(delay=rand(40, 100))
                self._log('GeeTest: clicked user selector button')
                return True
            else:
                self._log('GeeTest: user selector element not found on page:', css)

        for css in self._CHECKBOX_SELECTORS:
            btn = await page.query_selector(css)
            if btn:
                visible = await btn.is_visible()
                if not visible:
                    continue
                self._log('GeeTest: found checkbox via selector:', css)
                await btn.scroll_into_view_if_needed()
                await sleep(rand(200, 500))
                await btn.click(delay=rand(40, 100))
                self._log('GeeTest: clicked checkbox button')
                return True

        self._log('GeeTest: no checkbox/button found to click')
        return False

    async def _attempt(self) -> bool:
        page = self.page
        captcha_type = await self._detect_type(page)

        if captcha_type == 'UNKNOWN':
            clicked = await self._click_checkbox(page)
            if clicked:
                self._log('GeeTest: waiting for captcha window to appear...')

            for _ in range(50):
                captcha_type = await self._detect_type(page)
                if captcha_type not in ('UNKNOWN', 'GEETEST_CHECKBOX_V3', 'GEETEST_CHECKBOX_V4'):
                    break
                await sleep(300)

            if captcha_type in ('UNKNOWN', 'GEETEST_CHECKBOX_V3', 'GEETEST_CHECKBOX_V4'):
                raise RuntimeError('GeeTest: captcha window not found or unknown type')

        if captcha_type in ('GEETEST_CHECKBOX_V3', 'GEETEST_CHECKBOX_V4'):
            self._log('GeeTest: checkbox detected, clicking to open challenge...')
            clicked = await self._click_checkbox(page)
            if not clicked:
                raise RuntimeError('GeeTest: checkbox found but could not click it')
            for _ in range(50):
                captcha_type = await self._detect_type(page)
                if captcha_type not in ('UNKNOWN', 'GEETEST_CHECKBOX_V3', 'GEETEST_CHECKBOX_V4'):
                    break
                await sleep(300)
            if captcha_type in ('UNKNOWN', 'GEETEST_CHECKBOX_V3', 'GEETEST_CHECKBOX_V4'):
                success = await self._check_success(page)
                if success:
                    return True
                raise RuntimeError('GeeTest: captcha window not found after clicking checkbox')

        self._log('GeeTest detected type:', captcha_type)

        if captcha_type == 'GEETEST_VERSION_3_SLIDER':
            return await self._v3_slider(page)
        if captcha_type == 'GEETEST_VERSION_4_SLIDER':
            return await self._v4_slider(page)
        if captcha_type == 'GEETEST_VERSION_3_CLICK':
            return await self._v3_click(page)
        if captcha_type == 'GEETEST_VERSION_4_CLICK':
            return await self._v4_click(page)
        if captcha_type == 'GEETEST_VERSION_4_SWAP_ITEMS':
            return await self._v4_swap(page)
        raise RuntimeError(f'GeeTest: unknown type "{captcha_type}"')

    async def _v3_slider(self, page: Page) -> bool:
        canvas_sel = "div[class*='geetest_holder'][class*='geetest_ant'] :first-child[class*='geetest_canvas_bg']"
        canvas_el = await wait_for_element(page, f'>CSS> {canvas_sel}', 10000)
        if not canvas_el:
            raise RuntimeError('GeeTest V3 Slider: canvas not found')

        bg_b64 = await page.evaluate("""(sel) => {
            const c = document.querySelector(sel);
            if (!c || c.tagName !== 'CANVAS') return null;
            return c.toDataURL('image/png').replace(/^data:image[/](png|jpg|jpeg);base64,/, '');
        }""", canvas_sel)
        if not bg_b64:
            bg_b64 = await screenshot_element(canvas_el)

        dims = await page.evaluate("""(sel) => {
            const c = document.querySelector(sel);
            if (!c) return { sent: 0, disp: 0 };
            const sent = c.width || 0;
            const disp = c.offsetWidth || c.clientWidth || c.getBoundingClientRect().width || 0;
            return { sent: sent, disp: disp };
        }""", canvas_sel)
        sent_img_w = dims.get('sent', 0) or 360
        display_w = dims.get('disp', 0) or sent_img_w

        raw_result = await self.client.solve_coordinates_raw(
            body0=bg_b64, click='geetest', textinstructions='Slider', coordinatescaptcha='1', debug=self.debug
        )
        if not raw_result:
            raise RuntimeError('GeeTest V3 Slider: empty API result')
        self._log('GeeTest V3 Slider raw result:', raw_result)

        nums = self.client._parse_raw_pixel_coords(raw_result)
        if len(nums) < 2:
            raise RuntimeError(f'GeeTest V3 Slider: bad result: {raw_result}')

        answer_x = nums[0]

        if sent_img_w > 0 and display_w > 0:
            drag_px = round(answer_x / sent_img_w * display_w)
        else:
            drag_px = answer_x

        self._log(f'GeeTest V3 Slider: answer_x={answer_x} sent_w={sent_img_w} display_w={display_w} drag_px={drag_px}')

        btn_el = await page.query_selector("[class*='geetest_slider_button']")
        if not btn_el:
            raise RuntimeError('GeeTest V3 Slider: slider button not found')

        btn_box = await btn_el.bounding_box()
        start_x = btn_box['x'] + btn_box['width'] / 2
        start_y = btn_box['y'] + btn_box['height'] / 2

        await self._drag_precise(page, start_x, start_y, start_x + drag_px, start_y)
        await sleep(rand(500, 1000))

        refresh_el = await page.query_selector("a[class*='geetest_refresh']")
        if refresh_el:
            self._log('GeeTest V3 Slider: wrong answer, retrying...')
            await refresh_el.click()
            await sleep(rand(1000, 2000))
            return False

        return await self._check_success(page)

    async def _v4_slider(self, page: Page) -> bool:
        btn_sel = "[class*='geetest_box'][style*='block'] [class*='geetest_btn']"
        btn_el = await wait_for_element(page, f'>CSS> {btn_sel}', 10000)
        if not btn_el:
            raise RuntimeError('GeeTest V4 Slider: btn not found')

        for _ in range(20):
            has_bg = await page.evaluate("""() => {
                const box = document.querySelector("[class*='geetest_box'][style*='block']");
                if (!box) return false;
                for (const el of box.querySelectorAll("*")) {
                    const bg = window.getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none' && bg.includes('url') && !bg.includes('gradient')) return true;
                }
                const cv = box.querySelector("canvas");
                return !!(cv && cv.width > 0);
            }""")
            if has_bg:
                break
            await sleep(300)

        geo = await page.evaluate("""() => {
            const box = document.querySelector("[class*='geetest_box'][style*='block']");
            if (!box) return {};
            const result = {};

            const btn = box.querySelector("[class*='geetest_btn']");
            if (btn) {
                result.btnW = btn.getBoundingClientRect().width;
                result.btnH = btn.getBoundingClientRect().height;
            }
            const track = box.querySelector("[class*='geetest_track']");
            if (track) {
                result.trackW = track.getBoundingClientRect().width;
            }

            // Canvas: buffer size (sent) and CSS display size
            const canvas = box.querySelector("canvas");
            if (canvas && canvas.width > 0) {
                result.canvasW = canvas.width;
                result.canvasH = canvas.height;
                result.canvasDisplayW = canvas.offsetWidth || canvas.clientWidth || canvas.getBoundingClientRect().width;
                try { result.canvasB64 = canvas.toDataURL('image/png').split(',')[1]; } catch(e) {}
            }

            // Background image URL and its element display size
            for (const el of box.querySelectorAll("*")) {
                const bg = window.getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none' && bg.includes('url') && !bg.includes('gradient')) {
                    const url = bg.replace(/^url\\(["']?/, '').replace(/["']?\\)$/, '');
                    const r = el.getBoundingClientRect();
                    if (r.width > 100) {
                        result.bgUrl = url;
                        result.bgElemW = r.width;
                        result.bgElemH = r.height;
                        break;
                    }
                }
            }
            return result;
        }""")
        self._log('GeeTest V4 Slider geo:', {k: v for k, v in geo.items() if k not in ('canvasB64',)})

        bg_b64 = geo.get('canvasB64')
        sent_img_w = geo.get('canvasW', 0)
        display_w = geo.get('canvasDisplayW', 0)

        if not bg_b64 and geo.get('bgUrl'):
            self._log('GeeTest V4 Slider: fetching bg from:', geo['bgUrl'][:80])
            try:
                bg_b64 = await self._url_to_base64(geo['bgUrl'])
                img_size = await page.evaluate("""(url) => new Promise((resolve) => {
                    const img = new Image();
                    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
                    img.onerror = () => resolve({ w: 0, h: 0 });
                    img.src = url;
                })""", geo['bgUrl'])
                sent_img_w = img_size.get('w', 0)
                display_w = geo.get('bgElemW', 0)
                self._log(f'GeeTest V4 Slider: bg natural={sent_img_w}x{img_size.get("h",0)} display={display_w}')
            except Exception as e:
                self._log('GeeTest V4 Slider: bg fetch failed:', e)

        if not bg_b64:
            for sel in [
                "[class*='geetest_box'][style*='block'] [class*='geetest_window']",
                "[class*='geetest_box'][style*='block']",
            ]:
                bg_el = await page.query_selector(sel)
                if bg_el:
                    bg_b64 = await screenshot_element(bg_el)
                    ss_box = await bg_el.bounding_box()
                    if ss_box:
                        sent_img_w = int(ss_box['width'])
                        display_w = int(ss_box['width'])
                    self._log('GeeTest V4 Slider: screenshot fallback via:', sel)
                    break

        if not bg_b64:
            raise RuntimeError('GeeTest V4 Slider: background image not found')

        raw_result = await self.client.solve_coordinates_raw(
            body0=bg_b64, click='geetest', textinstructions='Slider', coordinatescaptcha='1', debug=self.debug
        )
        if not raw_result:
            raise RuntimeError('GeeTest V4 Slider: empty API result')
        self._log('GeeTest V4 Slider raw result:', raw_result)

        nums = self.client._parse_raw_pixel_coords(raw_result)
        if not nums:
            raise RuntimeError(f'GeeTest V4 Slider: bad result: {raw_result}')

        answer_x = nums[0]

        if sent_img_w > 0 and display_w > 0:
            drag_px = round(answer_x / sent_img_w * display_w)
        else:
            drag_px = answer_x

        self._log(f'GeeTest V4 Slider: answer_x={answer_x} sent_w={sent_img_w} display_w={display_w} drag_px={drag_px}')

        btn_box = await btn_el.bounding_box()
        if not btn_box:
            await btn_el.scroll_into_view_if_needed()
            await sleep(300)
            btn_box = await btn_el.bounding_box()
        if not btn_box:
            raise RuntimeError('GeeTest V4 Slider: cannot get btn bounding box')
        start_x = btn_box['x'] + btn_box['width'] / 2
        start_y = btn_box['y'] + btn_box['height'] / 2

        await self._drag_precise(page, start_x, start_y, start_x + drag_px, start_y)
        await sleep(500)

        error_el = await page.query_selector(
            "div[class*='geetest_radar_error'][style*='width: 300'] [class*='geetest_reset_tip_content'],"
            "div[class*='geetest_panel_error'][style*='block'] [class*='geetest_panel_error_content'],"
            "[class*='geetest_box'][style*='block'] [class*='geetest_reset'],"
            "[class*='geetest_result_tips'][class*='geetest_fail'][class*='geetest_showResult']"
        )
        if error_el:
            self._log('GeeTest V4 Slider: wrong answer, clicking error to retry...')
            await error_el.click()
            await sleep(rand(1000, 2000))
            return False
    async def _v3_click(self, page: Page) -> bool:
        container_sel = "div[class*='geetest_silver'][style*='block']"
        container_el = await wait_for_element(page, f'>CSS> {container_sel}', 10000)
        if not container_el:
            raise RuntimeError('GeeTest V3 Click: container not found')

        b64 = await screenshot_element(container_el)
        container_box = await container_el.bounding_box()

        raw_result = await self.client.solve_coordinates_raw(
            body0=b64, click='geetest', textinstructions='geetestv2', coordinatescaptcha='1', debug=self.debug
        )
        self._log('GeeTest V3 Click raw result:', raw_result)
        if not raw_result or 'ERROR' in raw_result:
            raise RuntimeError(f'GeeTest V3 Click: bad API result: {raw_result}')

        coord_str = raw_result.split('coordinates:')[1] if 'coordinates:' in raw_result else raw_result
        pairs = [p.strip() for p in coord_str.split(';') if p.strip()]

        for pair in pairs:
            x_val, y_val = 0, 0
            for part in pair.split(','):
                part = part.strip()
                if part.startswith('x='): x_val = int(re.sub(r'[^0-9]', '', part[2:]))
                elif part.startswith('y='): y_val = int(re.sub(r'[^0-9]', '', part[2:]))
            await human_click(page, container_box['x'] + x_val, container_box['y'] + y_val)
            await sleep(rand(200, 500))

        await sleep(rand(300, 600))
        submit_el = await page.query_selector("div[class*='geetest_silver'][style*='block'] [class*='geetest_commit_tip']")
        if submit_el:
            await submit_el.click(delay=rand(30, 80))
            await sleep(rand(1000, 2000))

        return await self._check_success(page)

    async def _v4_click(self, page: Page) -> bool:
        container_sel = "[class*='geetest_box_wrap'][style*='block'] :first-child[class*='geetest_box']"
        container_el = await wait_for_element(page, f'>CSS> {container_sel}', 10000)
        if not container_el:
            raise RuntimeError('GeeTest V4 Click: container not found')

        b64 = await screenshot_element(container_el)
        container_box = await container_el.bounding_box()

        submit_el = await page.query_selector("[class*='geetest_commit_tip'], [class*='geetest_submit']")
        text_instructions = 'geetesticonhand' if submit_el else 'geetesticonv4'

        raw_result = await self.client.solve_coordinates_raw(
            body0=b64, click='geetest', textinstructions=text_instructions, coordinatescaptcha='1', debug=self.debug
        )
        self._log('GeeTest V4 Click raw result:', raw_result)
        if not raw_result or 'ERROR' in raw_result:
            raise RuntimeError(f'GeeTest V4 Click: bad API result: {raw_result}')

        coord_str = raw_result.split('coordinates:')[1] if 'coordinates:' in raw_result else raw_result
        pairs = [p.strip() for p in coord_str.split(';') if p.strip()]

        for pair in pairs:
            x_val, y_val = 0, 0
            for part in pair.split(','):
                part = part.strip()
                if part.startswith('x='): x_val = int(re.sub(r'[^0-9]', '', part[2:]))
                elif part.startswith('y='): y_val = int(re.sub(r'[^0-9]', '', part[2:]))
            await human_click(page, container_box['x'] + x_val, container_box['y'] + y_val)
            await sleep(rand(200, 500))

        await sleep(rand(300, 600))
        if submit_el:
            await submit_el.click(delay=rand(30, 80))
            await sleep(rand(1000, 2000))

        return await self._check_success(page)

    async def _v4_swap(self, page: Page) -> bool:
        container_sel = "[class*='geetest_box'][style*='block'] [class*='geetest_container']"
        container_el = await wait_for_element(page, f'>CSS> {container_sel}', 10000)
        if not container_el:
            raise RuntimeError('GeeTest V4 Swap: container not found')

        b64 = await screenshot_element(container_el)
        container_box = await container_el.bounding_box()

        items = await page.query_selector_all("[class*='geetest_item_wrap']")
        is_five = len(items) >= 5
        text_instructions = 'five' if is_five else 'three'

        raw_result = await self.client.solve_coordinates_raw(
            body0=b64, click='geetest', textinstructions=text_instructions, coordinatescaptcha='1', debug=self.debug
        )
        self._log('GeeTest V4 Swap raw result:', raw_result)
        if not raw_result or 'ERROR' in raw_result:
            raise RuntimeError(f'GeeTest V4 Swap: bad API result: {raw_result}')

        coord_str = raw_result.split('coordinates:')[1] if 'coordinates:' in raw_result else raw_result
        pairs = [p.strip() for p in coord_str.split(';') if p.strip()]

        for pair in pairs:
            x_val, y_val = 0, 0
            for part in pair.split(','):
                part = part.strip()
                if part.startswith('x='): x_val = int(re.sub(r'[^0-9]', '', part[2:]))
                elif part.startswith('y='): y_val = int(re.sub(r'[^0-9]', '', part[2:]))
            await human_click(page, container_box['x'] + x_val, container_box['y'] + y_val)
            await sleep(rand(300, 700))

        await sleep(rand(800, 1500))
        return await self._check_success(page)

    async def _drag_precise(self, page: Page, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
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

    async def _check_success(self, page: Page) -> bool:
        if await page.query_selector("div[class*='geetest_lock_success'] [class*='geetest_holder']"):
            return True
        if await page.query_selector("div[class*='geetest_radar_success']"):
            return True
        if await page.query_selector(".geetest_success_radar_tip_content"):
            return True
        if await page.query_selector("[class*='geetest_success_animate']"):
            return True
        box = await page.query_selector("[class*='geetest_box'][style*='block'], div[class*='geetest_silver'][style*='block']")
        return box is None

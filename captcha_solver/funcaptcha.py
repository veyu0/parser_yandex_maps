from __future__ import annotations

import json
import random
import re
from typing import Optional

from playwright.async_api import Page, Frame

from .base_solver import CaptchaSolverBase
from .helpers import sleep, rand, wait_for_element, screenshot_element, human_click, random_mouse_wiggle

SEL_BUTTON = (
    '#home_children_button, '
    '#wrong_children_button, '
    '#wrongTimeout_children_button, '
    'button[data-theme*="verifyButton"], '
    '[class*="game-fail"] .button, '
    '.error .button'
)
SEL_TITLE = '#game_children_text h2, .tile-game h2, .match-game h2'
SEL_IMAGE = '#game_challengeItem_image, .challenge-container button, .key-frame-image'

SEL_ALL_GAME_ELEMENTS = [
    '#game_challengeItem',
    'div[class*="match-game box screen"]',
    'div[class*="tile-game box screen"]',
    'legend[id*="game-header"]',
    'a[id*="Frame_children_arrow"]',
]

SEL_WRONG_SOLVE = [
    '#wrong_children_exclamation',
    'div[class*="match-game-fail"]',
    'div[class*="tile-game-fail"]',
    'div[id*="descriptionTryAgain"]',
]

SEL_LOAD_ERROR = [
    'div[class*="error box screen"]',
    '#sub-frame-error',
    '#timeout_widget',
]

GAME_BOX_TASKS = [
    'coordinatesmatch', 'orbit_match_game', 'seat_coordinates',
    'train_coordinates', 'iconrace', '3d_rollball_objects',
]

class FuncaptchaSolver(CaptchaSolverBase):

    async def solve(self, selector: str = '') -> bool:
        self._log('Solving FunCaptcha...')
        await random_mouse_wiggle(self.page)
        for attempt in range(self.attempts):
            self._log(f'Attempt {attempt + 1}/{self.attempts}')
            try:
                if await self._attempt(selector or self.selector):
                    self._log('FunCaptcha solved!')
                    return True
            except Exception as e:
                self._log('Error:', e)
                if attempt < self.attempts - 1:
                    await sleep(rand(1500, 3000))
        raise RuntimeError('FunCaptcha: failed. Error: ERROR_CAPTCHA_UNSOLVABLE')

    async def _attempt(self, sel: str) -> bool:
        page = self.page
        funcaptcha_task_data: dict = {}

        async def _capture_funcaptcha(response):
            try:
                url = response.url
                if '/fc/gfc/' in url or '/fc/ca/' in url or 'funcaptcha' in url:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct or 'text' in ct:
                        body = await response.text()
                        if body and 'game_data' in body:
                            try:
                                data = json.loads(body)
                                if isinstance(data, dict) and 'game_data' in data:
                                    gd = data['game_data']
                                    if gd.get('game_variant'):
                                        funcaptcha_task_data['task'] = gd['game_variant']
                                        funcaptcha_task_data['waves'] = gd.get('waves', 1)
                                    elif gd.get('instruction_string'):
                                        funcaptcha_task_data['task'] = gd['instruction_string']
                                        funcaptcha_task_data['waves'] = gd.get('waves', 1)
                            except (json.JSONDecodeError, KeyError):
                                pass
            except Exception:
                pass

        page.on('response', _capture_funcaptcha)
        try:
            return await self._eStart(page, funcaptcha_task_data)
        finally:
            page.remove_listener('response', _capture_funcaptcha)

    async def _eStart(self, page: Page, funcaptcha_task_data: dict, n: int = 25) -> bool:

        await self._click_captcha_trigger(page)

        frame = await self._get_func_frame(page)

        await self._wait_for_task_load(funcaptcha_task_data)

        await self._click_verify_button(page, frame)

        await self._sendButton(frame, max_tries=2)

        funcaptcha_type = await self._detect_funcaptcha_type(frame, funcaptcha_task_data)
        if not funcaptcha_type:
            ver = await self._detectCaptcha(frame)
            if ver is None:
                if await self._check_green_tick(frame):
                    self._log('Captcha already solved (green tick)')
                    return True
                self._log('detectCaptcha: type not found')
                return False
            funcaptcha_type = {0: 'Game_Item', 1: 'Game_Tile', 2: 'Game_Box'}.get(ver, 'Game_Box')

        self._log(f'FunCaptcha type: {funcaptcha_type}')

        task = await self._getTaskTest(frame, funcaptcha_task_data)
        if not task:
            self._log('getTaskTest: task not found')
            return False
        self._log(f'Task: {task}')

        click_method = 'funcap'
        self._log(f'API click method: {click_method}')

        img_old = ''
        first_load = True

        for i in range(n):
            self._log(f'Solve iteration {i + 1}/{n}')

            if not first_load:
                if await self._check_wrong_solve(frame):
                    self._log('Solved incorrectly')
                    return False

            if not first_load and i > 0:
                if await self._check_green_tick(frame):
                    self._log('GREEN TICK — solved!')
                    return True

            if await self._check_load_errors(frame):
                self._log('Load error detected')
                error_btn = await frame.query_selector('div[class*="error box screen"] button')
                if error_btn:
                    try:
                        await error_btn.click(delay=rand(30, 80))
                        await sleep(1500)
                    except Exception:
                        pass
                continue

            btn_check = await frame.query_selector(SEL_BUTTON)
            if btn_check:
                self._log('Button reappeared, clicking...')
                await self._sendButton(frame, max_tries=1)
                await sleep(1000)
                img_old = ''

            img = await self._get_image_for_type(frame, funcaptcha_type)

            if img and img_old and img_old == img:
                self._log('Same image. Checking...')
                await sleep(1000)
                if await self._check_green_tick(frame):
                    self._log('GREEN TICK after same image — solved!')
                    return True
                check_btn = await frame.query_selector(SEL_BUTTON)
                if not check_btn:
                    self._log('No button — solved')
                    return True
                continue

            if not img:
                self._log('No image found, checking...')
                await sleep(1000)
                if await self._check_green_tick(frame):
                    self._log('GREEN TICK (no image) — solved!')
                    return True
                if not await frame.query_selector(SEL_IMAGE):
                    self._log('selImage gone — solved')
                    return True
                self._log('selImage present but no image data — Error 5')
                return False

            first_load = False

            api_params = {
                'type': 'base64',
                'click': click_method,
                'textinstructions': task,
                'body': img,
            }

            result = await self.client.click(api_params, debug=self.debug)

            if (result
                    and str(result).strip() != ''
                    and str(result).strip() != 'WAIT'
                    and 'ERROR' not in str(result).upper()):
                res_str = str(result).strip()
                self._log(f'API result: {res_str}')

                if 'coordinates' in res_str:
                    x_match = re.search(r'x=(\d+)', res_str)
                    y_match = re.search(r'y=(\d+)', res_str)
                    if x_match and y_match:
                        x = int(x_match.group(1))
                        y = int(y_match.group(1))
                        self._log(f'Parsed coordinates: x={x}, y={y}')

                        if funcaptcha_type in ('Game_Box', 'Game_Children'):
                            img_width = 300
                            num = x // img_width
                            self._log(f'Coordinates → image index: {num} (click arrow {num} times)')

                            if funcaptcha_type == 'Game_Children':
                                arrow_sel = 'a[id*="children_arrowRight"]'
                                submit_sel = '#game_children_buttonContainer button'
                            else:
                                arrow_sel = '.right-arrow'
                                submit_sel = '.button'

                            arrow = await frame.query_selector(arrow_sel)
                            btn_submit = await frame.query_selector(submit_sel)
                            if arrow and btn_submit:
                                for _ in range(num):
                                    await arrow.click()
                                    await sleep(150)
                                await btn_submit.click(delay=rand(30, 80))
                                self._log(f'Clicked arrow {num} times, then submit')
                            else:
                                self._log(f'Arrow or submit not found')

                        else:
                            col = x // 100
                            row = y // 100
                            cell_index = row * 3 + col
                            self._log(f'Coordinates → cell index: {cell_index}')

                            if funcaptcha_type == 'Game_Item':
                                cells = await frame.query_selector_all('#game_children_challenge a')
                            elif funcaptcha_type == 'Game_Tile':
                                cells = await frame.query_selector_all('.challenge-container button')
                            elif funcaptcha_type == 'Game_Lite':
                                cells = await frame.query_selector_all('fieldset > div input, fieldset > div label')
                            else:
                                cells = await frame.query_selector_all('.challenge-container button')

                            if 0 <= cell_index < len(cells):
                                await cells[cell_index].click(delay=rand(30, 80))
                                self._log(f'Clicked cell {cell_index}')

                else:
                    num = self._parse_index(res_str)

                    if num is not None:
                        if funcaptcha_type in ('Game_Item',):
                            cells = await frame.query_selector_all('#game_children_challenge a')
                            if 0 <= num < len(cells):
                                await cells[num].click(delay=rand(30, 80))
                                self._log(f'Clicked cell index: {num}')

                        elif funcaptcha_type in ('Game_Tile',):
                            cells = await frame.query_selector_all('.challenge-container button')
                            if 0 <= num < len(cells):
                                await cells[num].click(delay=rand(30, 80))
                                self._log(f'Clicked cell index: {num}')

                        elif funcaptcha_type in ('Game_Box', 'Game_Children'):
                            if funcaptcha_type == 'Game_Children':
                                arrow_sel = 'a[id*="children_arrowRight"]'
                                submit_sel = '#game_children_buttonContainer button'
                            else:
                                arrow_sel = '.right-arrow'
                                submit_sel = '.button'

                            arrow = await frame.query_selector(arrow_sel)
                            btn_submit = await frame.query_selector(submit_sel)
                            if arrow and btn_submit:
                                for _ in range(num):
                                    await arrow.click()
                                    await sleep(150)
                                await btn_submit.click(delay=rand(30, 80))
                                self._log(f'Clicked arrow {num} times, then submit')

                        elif funcaptcha_type == 'Game_Lite':
                            cells = await frame.query_selector_all('fieldset > div input, fieldset > div label')
                            if 0 <= num < len(cells):
                                await cells[num].click(delay=rand(30, 80))
                                self._log(f'Clicked cell index: {num}')
            else:
                self._log(f'API Error or WAIT: {result}')

            img_old = img
            await sleep(1500)

            if await self._check_green_tick(frame):
                self._log('GREEN TICK after solve — solved!')
                return True

            has_image = await frame.query_selector(SEL_IMAGE)
            has_title = await frame.query_selector(SEL_TITLE)
            if not has_image and not has_title:
                self._log('Elements gone — solved')
                return True

        await sleep(1000)
        self._log('Loop exhausted')
        return True

    async def _detect_funcaptcha_type(self, frame, funcaptcha_task_data: dict) -> Optional[str]:
        task = funcaptcha_task_data.get('task', '')
        if task:
            for box_task in GAME_BOX_TASKS:
                if box_task in task:
                    return 'Game_Box'

        type_selectors = [
            ('#game_challengeItem', 'Game_Item'),
            ('div[class*="match-game box screen"]', 'Game_Box'),
            ('div[class*="tile-game box screen"]', 'Game_Tile'),
            ('legend[id*="game-header"]', 'Game_Lite'),
            ('a[id*="Frame_children_arrow"]', 'Game_Children'),
        ]
        for attempt in range(40):
            for sel, ftype in type_selectors:
                try:
                    el = await frame.query_selector(sel)
                    if el and await el.is_visible():
                        return ftype
                except Exception:
                    pass
            await sleep(200)
        return None

    async def _get_image_for_type(self, frame, funcaptcha_type: str) -> Optional[str]:
        """
        cap.guru funcap.js строки 134-143:
          ver==0: getImageSrc() — берёт src элемента
          ver==1/2: extractImageToCanvas(.challenge-container button, .key-frame-image)
        """
        if funcaptcha_type == 'Game_Item':
            return await self._getImageSrc(frame)

        elif funcaptcha_type in ('Game_Box', 'Game_Tile'):
            min_size = 50000 if funcaptcha_type == 'Game_Box' else 5000
            for attempt in range(30):
                img_el = await frame.query_selector('.challenge-container button, .key-frame-image')
                if img_el:
                    b64 = await self._extractImageToCanvas(frame, img_el)
                    if b64 and len(b64) > min_size:
                        self._log(f'Got image (size: {len(b64)} chars, attempt {attempt + 1})')
                        return b64
                    elif b64:
                        self._log(f'Image too small ({len(b64)} chars, need >{min_size}), waiting...')
                await sleep(500)
            img_el = await frame.query_selector('.challenge-container button, .key-frame-image')
            if img_el:
                b64 = await self._extractImageToCanvas(frame, img_el)
                if b64:
                    self._log(f'Fallback image (size: {len(b64)} chars)')
                    return b64
            return None

        elif funcaptcha_type == 'Game_Children':
            for _ in range(20):
                img_el = await frame.query_selector('img[id*="children_challengeImage"]')
                if img_el:
                    b64 = await self._extractImageToCanvas(frame, img_el)
                    if b64:
                        return b64
                await sleep(300)
            return None

        elif funcaptcha_type == 'Game_Lite':
            for _ in range(20):
                b64 = await frame.evaluate("""() => {
                    const el = document.querySelector('img[id*="challenge-image"]');
                    if (!el) return null;
                    if (el.src && el.src.startsWith('data:image')) {
                        return el.src.replace(/data:image\\/[a-z]+;base64,/g, '');
                    }
                    return null;
                }""")
                if b64:
                    return b64
                await sleep(300)
            return None

        return await self._getImageSrc(frame)

    async def _click_captcha_trigger(self, page: Page) -> bool:
        for attempt in range(15):
            for sel in ['iframe[src*="arkoselabs"]', 'iframe[src*="funcaptcha"]', 'iframe[data-src*="octocaptcha"]']:
                if await page.query_selector(sel):
                    return True
            if self.selector:
                try:
                    trigger = await page.query_selector(self.selector)
                    if trigger and await trigger.is_visible():
                        self._log(f'Clicking trigger: {self.selector}')
                        await human_click(page, trigger)
                        await sleep(rand(1500, 2500))
                        return True
                except Exception:
                    pass
            await sleep(rand(500, 800))
        return False

    async def _wait_for_task_load(self, funcaptcha_task_data: dict, max_wait_ms: int = 15000) -> bool:
        elapsed = 0
        while elapsed < max_wait_ms:
            if funcaptcha_task_data.get('task'):
                self._log(f'Task loaded from network after {elapsed}ms')
                return True
            await sleep(200)
            elapsed += 200
        self._log(f'Task not from network after {max_wait_ms}ms')
        return False

    async def _click_verify_button(self, page: Page, frame) -> None:
        for sel in ['#verifyButton', 'button[data-theme*="verifyButton"]']:
            try:
                btn = await frame.query_selector(sel)
                if btn and await btn.is_visible():
                    self._log(f'Clicking {sel}')
                    await btn.click(delay=rand(30, 80))
                    await sleep(2000)
                    return
            except Exception:
                pass
        for iframe_sel in ['iframe[src*="enforcementFrame"]', 'iframe[src*="arkoselabs"]']:
            try:
                el = await page.query_selector(iframe_sel)
                if el:
                    ef = await el.content_frame()
                    if ef:
                        for sel in ['#verifyButton', 'button[data-theme*="verifyButton"]']:
                            btn = await ef.query_selector(sel)
                            if btn and await btn.is_visible():
                                await btn.click(delay=rand(30, 80))
                                await sleep(2000)
                                return
            except Exception:
                pass

    async def _check_green_tick(self, frame) -> bool:
        for sel in SEL_ALL_GAME_ELEMENTS:
            try:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    return False
            except Exception:
                return False
        return True

    async def _check_wrong_solve(self, frame) -> bool:
        for sel in SEL_WRONG_SOLVE:
            try:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _check_load_errors(self, frame) -> bool:
        for sel in SEL_LOAD_ERROR:
            try:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _get_func_frame(self, page: Page):
        for attempt in range(20):
            for iframe_sel in [
                'iframe[src*="arkoselabs"]', 'iframe[src*="funcaptcha"]',
                'iframe[id*="enforcementFrame"]', 'iframe[data-src*="octocaptcha"]',
            ]:
                try:
                    el = await page.query_selector(iframe_sel)
                    if el:
                        f1 = await el.content_frame()
                        if f1:
                            inner = await f1.query_selector('iframe')
                            if inner:
                                f2 = await inner.content_frame()
                                if f2:
                                    gc = await f2.query_selector('#game-core-frame, iframe[src*="game-core"]')
                                    if gc:
                                        f3 = await gc.content_frame()
                                        if f3:
                                            self._log('Found game-core-frame (3 levels)')
                                            return f3
                                    if await f2.query_selector('#game_challengeItem, .tile-game, .match-game, legend[id*="game-header"]'):
                                        self._log('Found game frame (2 levels)')
                                        return f2
                            gc = await f1.query_selector('#game-core-frame, iframe[src*="game-core"]')
                            if gc:
                                f2 = await gc.content_frame()
                                if f2:
                                    self._log('Found game-core-frame (2 levels)')
                                    return f2
                            if await f1.query_selector('#game_challengeItem, .tile-game, .match-game, legend[id*="game-header"]'):
                                self._log('Found game frame (1 level)')
                                return f1
                except Exception:
                    pass
            if attempt < 19:
                await sleep(500)
        for iframe_sel in ['iframe[src*="arkoselabs"]', 'iframe[src*="funcaptcha"]']:
            el = await page.query_selector(iframe_sel)
            if el:
                f = await el.content_frame()
                if f:
                    return f
        return page

    async def _sendButton(self, frame, max_tries: int = 5) -> bool:
        if not await frame.query_selector(SEL_BUTTON):
            return True
        for _ in range(max_tries):
            btn = await frame.query_selector(SEL_BUTTON)
            if not btn:
                return True
            try:
                if not await btn.is_visible():
                    return True
                await btn.click(delay=rand(30, 80))
                self._log('Clicked start/retry button')
                await sleep(1000)
                if not await frame.query_selector(SEL_BUTTON):
                    return True
            except Exception as e:
                self._log('Button click error:', e)
            await sleep(1000)
        return False

    async def _detectCaptcha(self, frame) -> Optional[int]:
        for _ in range(20):
            for sel, val in [('script[src*="tile-game-ui"]', 0), ('.tile-game', 1), ('.match-game', 2)]:
                if await frame.query_selector(sel):
                    return val
            await sleep(500)
        return None

    async def _getTaskTest(self, frame, funcaptcha_task_data: dict) -> str:
        task = funcaptcha_task_data.get('task', '')
        if task:
            return task
        for _ in range(20):
            try:
                el = await frame.query_selector(SEL_TITLE)
                if el:
                    text = re.sub(r'\s+', ' ', (await el.inner_text())).strip()
                    if text:
                        return text
            except Exception:
                pass
            await sleep(200)
        return funcaptcha_task_data.get('task', '')

    async def _getImageSrc(self, frame) -> Optional[str]:
        for _ in range(20):
            b64 = await frame.evaluate("""() => {
                const el = document.querySelector('#game_challengeItem_image, .challenge-container button, .key-frame-image');
                if (!el) return null;
                if ('src' in el && el.src != null && el.src !== '') {
                    return el.src.replace(/data:image\\/[a-z]+;base64,/g, '');
                }
                return null;
            }""")
            if b64:
                return b64
            await sleep(500)
        return None

    async def _extractImageToCanvas(self, frame, img_el) -> Optional[str]:
        """
        Порт extractImageToCanvas() + canToBasa64() из cap.guru funcap.js (строки 287-391).
        
        Берёт background-image из CSS элемента:
        1. Если data:image → вытаскиваем base64 напрямую из CSS
        2. Если CSSImageValue (blob) → рисуем через computedStyleMap → canvas
        3. Если same-origin URL → Image → canvas
        4. Если blob/cross-origin URL → fetch() → FileReader → base64
           (аналог sendMessageToExtension("fetch::asData") в cap.guru)
        """
        b64 = await frame.evaluate("""async (el) => {
            // Утилита: рендер в canvas → base64
            function tryCanvasRender(imgObj, w, h) {
                try {
                    if (!w || !h) return null;
                    let c = document.createElement('canvas');
                    c.width = w; c.height = h;
                    let ctx = c.getContext('2d');
                    ctx.drawImage(imgObj, 0, 0);
                    try {
                        let d = ctx.getImageData(0, 0, 1, 1).data;
                        if (d[3] === 0) return null;
                    } catch(e) { return null; }
                    return c.toDataURL('image/jpeg').replace(/data:image\\/[a-z]+;base64,/g, '');
                } catch(e) { return null; }
            }

            // Утилита: fetch URL → base64
            async function fetchAsBase64(url) {
                try {
                    let resp = await fetch(url);
                    let blob = await resp.blob();
                    return await new Promise((resolve) => {
                        let reader = new FileReader();
                        reader.onloadend = () => {
                            let dataUrl = reader.result;
                            resolve(dataUrl ? dataUrl.replace(/data:[^;]+;base64,/g, '') : null);
                        };
                        reader.onerror = () => resolve(null);
                        reader.readAsDataURL(blob);
                    });
                } catch(e) { return null; }
            }

            // Шаг 1: получаем background-image из CSS
            let bg = getComputedStyle(el).backgroundImage;
            if (!bg || bg === 'none') {
                if ('src' in el && el.src) bg = 'url("' + el.src + '")';
                else return null;
            }

            // Шаг 2: CSSImageValue (blob URL) → canvas
            if ('computedStyleMap' in el && !/url\\(["']https?:\\/\\//.test(bg)) {
                try {
                    let styleImg = el.computedStyleMap().get('background-image');
                    if (styleImg instanceof CSSImageValue) {
                        let w = el.clientWidth, h = el.clientHeight;
                        if (w && h) {
                            let c = document.createElement('canvas');
                            c.width = w; c.height = h;
                            c.getContext('2d').drawImage(styleImg, 0, 0);
                            try {
                                let d = c.getContext('2d').getImageData(0, 0, 1, 1).data;
                                if (d[3] !== 0) {
                                    let r = c.toDataURL('image/jpeg').replace(/data:image\\/[a-z]+;base64,/g, '');
                                    if (r) return r;
                                }
                            } catch(e) {}
                        }
                    }
                } catch(e) {}
            }

            // Шаг 3: парсим URL из background-image
            let urlMatch = /"(.+)"/.exec(bg);
            if (!urlMatch) return null;
            let imageUrl = urlMatch[1];

            // Если data:image → base64 прямо из CSS
            if (imageUrl.startsWith('data:image'))
                return imageUrl.replace(/data:[^;]+;base64,/g, '');

            // Шаг 4: same-origin URL → Image → canvas
            try {
                let a = document.createElement('a'); a.href = imageUrl;
                if (new URL(a.href).origin === document.location.origin) {
                    let img = new Image(); img.crossOrigin = 'anonymous'; img.src = imageUrl;
                    if (img.complete && img.naturalWidth > 0) {
                        let r = tryCanvasRender(img, img.naturalWidth, img.naturalHeight);
                        if (r) return r;
                    }
                }
            } catch(e) {}

            // Шаг 5: fetch URL (blob или cross-origin) → base64
            // Аналог cap.guru sendMessageToExtension("fetch::asData")
            let fetched = await fetchAsBase64(imageUrl);
            if (fetched) return fetched;

            return null;
        }""", img_el)

        if b64:
            return b64

        try:
            return await screenshot_element(img_el)
        except Exception:
            return None

    def _parse_index(self, result_str: str) -> Optional[int]:
        try:
            match = re.search(r'\d+', str(result_str))
            if match:
                return int(match.group()) - 1
        except Exception:
            pass
        return None

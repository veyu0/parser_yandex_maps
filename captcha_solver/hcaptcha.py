from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Optional

from playwright.async_api import Frame, Page

from .base_solver import CaptchaSolverBase
from .helpers import sleep, rand, random_mouse_wiggle

class HcaptchaSolver(CaptchaSolverBase):

    async def solve(self, selector: str = '') -> bool:
        self._log('Solving hCaptcha...')
        await random_mouse_wiggle(self.page)
        for attempt in range(self.attempts):
            self._log(f'Attempt {attempt + 1}/{self.attempts}')
            try:
                if await self._attempt():
                    self._log('hCaptcha solved!')
                    return True
            except Exception as e:
                self._log('Error:', e)
                if attempt < self.attempts - 1:
                    await sleep(rand(1500, 3000))
        raise RuntimeError('hCaptcha: failed. Error: ERROR_CAPTCHA_UNSOLVABLE')

    async def _find_frame(self, timeout: float = 10.0, selector_fn=None) -> Optional[Frame]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for f in self.page.frames:
                if 'hcaptcha.com' not in f.url:
                    continue
                try:
                    if selector_fn is None or await selector_fn(f):
                        return f
                except Exception:
                    pass
            await sleep(300)
        return None

    async def _is_solved(self, checkbox_frame: Optional[Frame]) -> bool:
        if checkbox_frame is None:
            for f in self.page.frames:
                if 'hcaptcha.com' not in f.url:
                    continue
                try:
                    solved = await f.evaluate("""() => {
                        const cb = document.querySelector('#checkbox');
                        if (cb && cb.getAttribute('aria-checked') === 'true') return true;
                        const div = document.querySelector('div.check');
                        if (div && div.style.display === 'block') return true;
                        return false;
                    }""")
                    if solved:
                        return True
                except Exception:
                    pass
            return False
        try:
            return await checkbox_frame.evaluate("""() => {
                const cb = document.querySelector('#checkbox');
                if (cb && cb.getAttribute('aria-checked') === 'true') return true;
                const div = document.querySelector('div.check');
                return !!(div && div.style.display === 'block');
            }""")
        except Exception:
            return False

    async def _switch_language(self, challenge_frame: Frame) -> None:
        try:
            lang = await challenge_frame.evaluate(
                "(document.documentElement.lang || navigator.language || '').toLowerCase()"
            )
            if lang.startswith('en'):
                return

            is_bbox   = bool(await challenge_frame.query_selector('.bounding-box-example'))
            is_header = bool(await challenge_frame.query_selector('.challenge-header'))
            is_9grid  = len(await challenge_frame.query_selector_all('.task-image .image')) == 9
            is_multi  = bool(await challenge_frame.query_selector('.task-answers'))

            if is_bbox or (is_header and not is_9grid) or is_multi or (not is_9grid):
                btn = await challenge_frame.query_selector('.display-language.button')
                if btn:
                    await challenge_frame.evaluate('el => el.click()', btn)
                    await sleep(200)

            opt = await challenge_frame.query_selector('.language-selector .option:nth-child(23)')
            if opt:
                await challenge_frame.evaluate('el => el.click()', opt)
                await sleep(300)

            await sleep(500)
            self._log('hCaptcha: switched language to English')
        except Exception as e:
            self._log('hCaptcha: language switch error:', e)

    async def _gather_data(self, challenge_frame: Frame) -> Optional[dict]:
        GET_BG_JS = """(el) => (el.style.backgroundImage || '').replace(/url\\("|"\\)/g, '')"""
        FETCH_B64_JS = """async (url) => {
            if (!url || url === 'none' || url === '') return null;
            try {
                const r = await fetch(url);
                if (!r.ok) return null;
                const blob = await r.blob();
                return await new Promise(res => {
                    const rd = new FileReader();
                    rd.readAsDataURL(blob);
                    rd.onloadend = () => res((rd.result||'').replace(/^data:image\\/(png|jpeg);base64,/, ''));
                    rd.onerror = () => res(null);
                });
            } catch(e) { return null; }
        }"""

        for _ in range(40):
            await sleep(500)
            try:
                prompt = await challenge_frame.evaluate("""() => {
                    const el = document.querySelector('h2.prompt-text') || document.querySelector('.prompt-text');
                    return el ? (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ') : '';
                }""")
                if not prompt:
                    continue

                is_bbox   = bool(await challenge_frame.query_selector('.bounding-box-example'))
                is_header = bool(await challenge_frame.query_selector('.challenge-header'))
                is_multi  = bool(await challenge_frame.query_selector('.task-answers'))
                task_imgs = await challenge_frame.query_selector_all('.task-image .image')
                is_9grid  = len(task_imgs) == 9

                images: dict[int, str] = {}
                examples: list[str] = []
                choices: list[str] = []

                if is_9grid or is_multi:
                    ok = True
                    for idx, tile_el in enumerate(task_imgs):
                        try:
                            buf = await tile_el.screenshot()
                            images[idx] = base64.b64encode(buf).decode()
                        except Exception:
                            ok = False; break
                    if not ok or not images:
                        continue
                    for ex_el in await challenge_frame.query_selector_all('.example-image .image'):
                        try:
                            buf = await ex_el.screenshot()
                            examples.append(base64.b64encode(buf).decode())
                        except Exception:
                            pass
                    if is_multi:
                        choices = await challenge_frame.evaluate(
                            "() => Array.from(document.querySelectorAll('.answer-text')).map(e=>(e.outerText||e.textContent||'').trim()).filter(Boolean)"
                        )
                    captcha_type = 'multi' if is_multi else 'grid'

                elif is_bbox or (is_header and not is_9grid):
                    b64 = await challenge_frame.evaluate("""() => {
                        const canvas = document.querySelector('canvas');
                        if (!canvas) return null;
                        try {
                            const d = canvas.getContext('2d',{willReadFrequently:true}).getImageData(0,0,canvas.width,canvas.height).data;
                            let mono=true;
                            for(let i=0;i<d.length;i+=4) if(d[i]!==d[i+1]||d[i+1]!==d[i+2]){mono=false;break;}
                            if(mono) return null;
                            const sw=parseInt(canvas.style.width,10)||canvas.width;
                            const sh=parseInt(canvas.style.height,10)||canvas.height;
                            if(sw<=0||sh<=0) return null;
                            const sc=Math.min(sw/canvas.width,sh/canvas.height);
                            const tw=canvas.width*sc, th=canvas.height*sc;
                            const tmp=document.createElement('canvas');
                            tmp.width=tw; tmp.height=th;
                            tmp.getContext('2d').drawImage(canvas,0,0,canvas.width,canvas.height,0,0,tw,th);
                            return tmp.toDataURL('image/jpeg').replace(/^data:image\\/(png|jpeg);base64,/,'');
                        } catch(e){ return null; }
                    }""")
                    if not b64 or len(b64) * 3 / 4 / 1024 < 10:
                        continue
                    images[0] = b64
                    for ex_el in await challenge_frame.query_selector_all('.example-image .image'):
                        url = await challenge_frame.evaluate(GET_BG_JS, ex_el)
                        if url and url != 'none':
                            b64ex = await challenge_frame.evaluate(FETCH_B64_JS, url)
                            if b64ex:
                                examples.append(b64ex)
                    captcha_type = 'bboxdd' if (is_header and not is_bbox) else 'bbox'

                elif task_imgs:
                    ok = True
                    for idx, tile_el in enumerate(task_imgs):
                        try:
                            buf = await tile_el.screenshot()
                            images[idx] = base64.b64encode(buf).decode()
                        except Exception:
                            ok = False; break
                    if not ok or not images:
                        continue
                    captcha_type = 'grid'
                else:
                    continue

                return {
                    'prompt': prompt, 'images': images, 'examples': examples,
                    'choices': choices, 'type': captcha_type, 'tiles': task_imgs,
                }
            except Exception as e:
                self._log('hCaptcha gather_data error:', e)

        return None

    async def _apply_answer(self, challenge_frame: Frame, data: dict, answer: str) -> str:
        answer = answer.strip()
        captcha_type = data.get('type', 'grid')

        if answer == 'notpic':
            await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
            await sleep(1200)
            return 'applied'

        if answer.startswith('coordinates:'):
            parts = [p.strip() for p in answer.replace('coordinates:', '').split(';') if p.strip()]
            await challenge_frame.evaluate("""async (parts) => {
                const canvas = document.querySelector('canvas');
                if (!canvas) return;
                const rect = canvas.getBoundingClientRect();
                for (const part of parts) {
                    const xm = part.match(/x=(\\d+)/), ym = part.match(/y=(\\d+)/);
                    if (!xm || !ym) continue;
                    const cx = parseInt(xm[1]) + rect.left, cy = parseInt(ym[1]) + rect.top;
                    canvas.dispatchEvent(new MouseEvent('mousedown', {clientX:cx, clientY:cy, bubbles:true, button:0}));
                    canvas.dispatchEvent(new MouseEvent('mouseup',   {clientX:cx, clientY:cy, bubbles:true, button:0}));
                    canvas.dispatchEvent(new MouseEvent('click',     {clientX:cx, clientY:cy, bubbles:true, button:0}));
                    await new Promise(r => setTimeout(r, 200 + 150 * Math.random()));
                }
            }""", parts)
            await sleep(500)
            await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
            await sleep(2500)
            return 'applied'

        if answer.startswith('move:'):
            pairs = []
            for part in answer.replace('move:', '').split(';'):
                xm = re.search(r'x=(\d+)', part)
                ym = re.search(r'y=(\d+)', part)
                pairs.append([int(xm.group(1)) if xm else 0, int(ym.group(1)) if ym else 0])
            if len(pairs) >= 2:
                await challenge_frame.evaluate("""async (pairs) => {
                    const canvas = document.querySelector('canvas');
                    if (!canvas || pairs.length < 2) return;
                    const rect = canvas.getBoundingClientRect();
                    for (let i = 0; i + 1 < pairs.length; i += 2) {
                        const ax=pairs[i][0]+rect.left, ay=pairs[i][1]+rect.top;
                        const bx=pairs[i+1][0]+rect.left, by=pairs[i+1][1]+rect.top;
                        canvas.dispatchEvent(new MouseEvent('mousedown',{clientX:ax,clientY:ay,bubbles:true,button:0,buttons:1}));
                        await new Promise(r=>setTimeout(r,100));
                        for(let s=1;s<=15;s++){
                            canvas.dispatchEvent(new MouseEvent('mousemove',{
                                clientX:ax+(bx-ax)/15*s, clientY:ay+(by-ay)/15*s, bubbles:true, buttons:1
                            }));
                            await new Promise(r=>setTimeout(r,30));
                        }
                        canvas.dispatchEvent(new MouseEvent('mouseup',{clientX:bx,clientY:by,bubbles:true,button:0}));
                        if(i+3<pairs.length) await new Promise(r=>setTimeout(r,1500));
                    }
                }""", pairs)
            await sleep(500)
            await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
            await sleep(2500)
            return 'applied'

        if captcha_type == 'multi':
            texts = [t.strip() for t in answer.split(',')]
            await challenge_frame.evaluate("""(texts) => {
                function fire(el){['mouseover','mousedown','mouseup','click'].forEach(type=>{
                    const e=document.createEvent('MouseEvents'); e.initEvent(type,true,false); el.dispatchEvent(e);
                });}
                const els=Array.from(document.querySelectorAll('.answer-text'));
                for(const t of texts){ const el=els.find(e=>(e.outerText||'').trim()===t); if(el) fire(el); }
            }""", texts)
            await sleep(500)
            await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
            await sleep(2500)
            return 'applied'

        if captcha_type == 'bbox':
            nums = [int(n) for n in re.split(r'[;:,]', answer) if n.strip().isdigit()]
            if len(nums) >= 2:
                await challenge_frame.evaluate("""(coords) => {
                    const canvas=document.querySelector('canvas');
                    if(!canvas) return;
                    const rect=canvas.getBoundingClientRect();
                    const opts={clientX:coords[0]+rect.left, clientY:coords[1]+rect.top, bubbles:true};
                    ['mouseover','mousedown','mouseup','click'].forEach(t=>canvas.dispatchEvent(new MouseEvent(t,opts)));
                }""", nums[:2])
            return 'applied'

        if captcha_type == 'bboxdd':
            await sleep(500)
            await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
            await sleep(2500)
            return 'applied'

        tile_indices = self.client._parse_tile_indices(answer)
        if tile_indices:
            tiles = data.get('tiles', [])
            for idx in tile_indices:
                if idx < len(tiles):
                    await sleep(rand(150, 350))
                    await challenge_frame.evaluate("""(el) => {
                        ['mouseover','mousedown','mouseup','click'].forEach(type=>{
                            const e=document.createEvent('MouseEvents'); e.initEvent(type,true,false); el.dispatchEvent(e);
                        });
                    }""", tiles[idx])
        await sleep(500)
        await challenge_frame.evaluate("() => { const b=document.querySelector('.button-submit'); b&&b.click(); }")
        await sleep(2500)
        return 'applied'

    async def _attempt(self) -> bool:
        page = self.page

        async def has_checkbox(f: Frame) -> bool:
            return bool(await f.query_selector('#checkbox, div.check'))

        async def has_prompt(f: Frame) -> bool:
            return bool(await f.query_selector('h2.prompt-text, .prompt-text'))

        checkbox_frame = await self._find_frame(timeout=3.0, selector_fn=has_checkbox)
        challenge_frame: Optional[Frame] = None

        if checkbox_frame:
            self._log('hCaptcha: checkbox frame found:', checkbox_frame.url[:80])

            if await self._is_solved(checkbox_frame):
                self._log('hCaptcha: already solved')
                return True

            self._log('Clicking hCaptcha checkbox...')
            await sleep(rand(300, 700))
            await checkbox_frame.evaluate("""() => {
                const cb = document.querySelector('#checkbox') || document.querySelector('div.check');
                if (cb) cb.click();
            }""")
            await sleep(rand(2000, 3500))

            if await self._is_solved(checkbox_frame):
                self._log('hCaptcha: solved without image challenge!')
                return True

            challenge_frame = await self._find_frame(timeout=15.0, selector_fn=has_prompt)
            if not challenge_frame:
                self._log('hCaptcha: challenge frame not found after checkbox click, checking if solved...')
                return await self._is_solved(checkbox_frame)
        else:
            self._log('hCaptcha: no checkbox frame, looking for challenge frame directly...')
            challenge_frame = await self._find_frame(timeout=10.0, selector_fn=has_prompt)
            if not challenge_frame:
                self._log('hCaptcha: neither checkbox nor challenge frame found')
                return False

        self._log('hCaptcha: challenge frame found:', challenge_frame.url[:80])

        fail_count = 0
        last_task_key: Optional[str] = None

        for iteration in range(15):
            await sleep(rand(300, 600))

            if await self._is_solved(checkbox_frame):
                self._log('hCaptcha: solved!')
                return True

            if not await challenge_frame.query_selector('h2.prompt-text, .prompt-text'):
                await sleep(1000)
                if await self._is_solved(checkbox_frame):
                    return True
                continue

            await self._switch_language(challenge_frame)

            self._log(f'hCaptcha: iteration {iteration + 1} — gathering data...')
            data = await self._gather_data(challenge_frame)

            if not data:
                self._log('hCaptcha: failed to gather data')
                fail_count += 1
                if fail_count >= 2:
                    self._log('hCaptcha: refreshing challenge')
                    await challenge_frame.evaluate("""() => {
                        const btn = document.querySelector('.refresh.button') ||
                                    document.querySelector('.button-submit') ||
                                    document.querySelector('[aria-label="Refresh"]');
                        if (btn) btn.click();
                    }""")
                    fail_count = 0
                    last_task_key = None
                await sleep(rand(800, 1500))
                continue

            self._log(f'hCaptcha: type={data["type"]}, prompt={data["prompt"]}, imgs={len(data["images"])}')

            task_key = json.dumps({'p': data['prompt'], 'k': list(data['images'].keys())})
            if task_key == last_task_key:
                await sleep(800)
            last_task_key = task_key

            sorted_keys = sorted(data['images'].keys())
            image_list = [data['images'][k] for k in sorted_keys]
            body = image_list[0] if len(image_list) == 1 else image_list

            payload: dict = {
                'type': 'base64',
                'textinstructions': data['prompt'],
            }

            if isinstance(body, list) and len(body) > 1:
                payload['click'] = 'hcap2'
                for i, b in enumerate(body):
                    payload[f'body{i}'] = b
            else:
                payload['click'] = 'hcap'
                payload['body'] = body[0] if isinstance(body, list) else body

            if data.get('examples'):
                payload['sizex'] = 10

            if data.get('choices'):
                payload['textinstructions'] += '|||' + ','.join(data['choices'])

            answer = await self.client.click(payload, debug=self.debug)
            self._log('hCaptcha: API answer:', answer)

            if not answer or 'ERROR' in answer:
                self._log('hCaptcha: no answer from API, fail count:', fail_count + 1)
                fail_count += 1
                if fail_count >= 2:
                    self._log('hCaptcha: refreshing challenge')
                    await challenge_frame.evaluate("""() => {
                        const btn = document.querySelector('.refresh.button') ||
                                    document.querySelector('.button-submit') ||
                                    document.querySelector('[aria-label="Refresh"]');
                        if (btn) btn.click();
                    }""")
                    fail_count = 0
                    last_task_key = None
                await sleep(rand(800, 1500))
                continue

            result = await self._apply_answer(challenge_frame, data, answer)
            self._log('hCaptcha: apply result:', result)

            if result == 'solved':
                return True

            fail_count = 0
            last_task_key = None

            await sleep(rand(500, 1000))
            if await self._is_solved(checkbox_frame):
                return True

        return await self._is_solved(checkbox_frame)

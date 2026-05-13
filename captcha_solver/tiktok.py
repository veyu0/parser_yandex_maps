from __future__ import annotations

import json
import re
from typing import Optional, Tuple, List

from playwright.async_api import Page

from .base_solver import CaptchaSolverBase
from .helpers import sleep, rand, wait_for_element, random_mouse_wiggle

OLD_CONTAINER = '.captcha_verify_container'
NEW_CONTAINER = '.TUXModal.captcha-verify-container'
FALLBACK_CONTAINERS = ', '.join([
    '#captcha_container',
    '#tiktok-verify-ele',
    '.captcha-disable-scroll',
    '[class*="captcha_verify_container"]',
    '[class*="captcha-verify-container"]',
    '[class*="secsdk-captcha"]',
])

DETECT_TYPE_JS = """() => {
    let c = document.querySelector('.TUXModal.captcha-verify-container');
    if (!c) c = document.querySelector('.captcha_verify_container');
    if (!c) c = document.querySelector('#captcha_container');
    if (!c) c = document.querySelector('[class*="captcha_verify_container"]');
    if (!c) return JSON.stringify({type:"unknown",isOld:false});
    const isOld = !!document.querySelector('.captcha_verify_container');
    const pp = c.querySelector('div[draggable="true"] img, div[draggable="true"] > img, .cap-justify-center div[draggable="true"] img');
    if (pp) { const s=window.getComputedStyle(pp); if(s.display!=='none'&&s.visibility!=='hidden') return JSON.stringify({type:"pazl",isOld}); }
    const imgs = Array.from(c.querySelectorAll('img'));
    const n = imgs.length;
    const circ = imgs.some(i=>(i.style?.clipPath||'').includes('circle'));
    const abs = imgs.some(i=>i.classList&&i.classList.contains('cap-absolute'));
    const wo = c.querySelector('[data-testid="whirl-outer-img"]');
    const wi = c.querySelector('[data-testid="whirl-inner-img"]');
    if ((wo&&wi)||(n>=2&&(circ||abs))) return JSON.stringify({type:"koleso",isOld});
    if (c.querySelector('.captcha_verify_img_slide')||c.querySelector('#captcha_slide_button')||c.querySelector('.secsdk-captcha-drag-icon')||c.querySelector('.cap-rounded-full > div')) return JSON.stringify({type:"slider",isOld});
    const it = (c.querySelector('span.cap-flex.cap-items-center')?.textContent||'').trim().toLowerCase();
    if (n===1&&!circ&&(it.includes('select')||it.includes('tap')||it.includes('object')||it.includes('выберите')||it.includes('нажмите'))) return JSON.stringify({type:"objects",isOld});
    if (n===1) return JSON.stringify({type:"abc",isOld});
    return JSON.stringify({type:"unknown",isOld});
}"""

GET_IMAGES_JS = """(captchaType) => {
    let c = document.querySelector('.TUXModal.captcha-verify-container')
        || document.querySelector('.captcha_verify_container')
        || document.querySelector('#captcha_container')
        || document.querySelector('[class*="captcha_verify_container"]');
    if (!c) return null;
    function b64(img){
        try{
            if(img.src&&img.src.startsWith('data:')){const m=img.src.match(/^data:[^,]+;base64,([\\s\\S]+)$/);if(m)return m[1];}
            const cv=document.createElement('canvas');cv.width=img.naturalWidth||img.width;cv.height=img.naturalHeight||img.height;
            cv.getContext('2d').drawImage(img,0,0);return cv.toDataURL('image/png').replace(/^data:image\\/\\w+;base64,/,'');
        }catch(e){
            if(img.src&&img.src.startsWith('blob:')){return null;}
            if(img.src&&img.src.startsWith('data:')){const m=img.src.match(/^data:[^,]+;base64,([\\s\\S]+)$/);return m?m[1]:null;}
            return null;
        }
    }
    let images=[],mainImg=null;
    if(captchaType==='koleso'){
        const o=c.querySelector('[data-testid="whirl-outer-img"]'),i2=c.querySelector('[data-testid="whirl-inner-img"]');
        if(o&&i2){images=[o,i2];}else{
            const a=Array.from(c.querySelectorAll('img'));
            const r=a.filter(i=>!i.classList.contains('cap-absolute')),ab=a.filter(i=>i.classList.contains('cap-absolute'));
            if(r.length>0)images.push(r[0]);if(ab.length>0)images.push(ab[0]);
            if(images.length<2&&a.length>=2)images=[a[0],a[1]];
        }
    }else if(captchaType==='pazl'){
        const m=c.querySelector('#captcha-verify-image')||c.querySelector('img.captcha_verify_img_slide')||c.querySelector('.cap-justify-center img')||c.querySelector('img');
        const p=c.querySelector('div[draggable="true"] img');
        if(m&&p)images=[m,p];else{const a=Array.from(c.querySelectorAll('img'));images=a.slice(0,2);}
        mainImg=images[0]||null;
    }else if(captchaType==='slider'){
        const m=c.querySelector('#captcha-verify-image')||c.querySelector('.captcha_verify_img_slide')||c.querySelector('img');
        if(m)images=[m];mainImg=m||null;
    }else{images=Array.from(c.querySelectorAll('img'));mainImg=images[0]||null;}
    const res={images:[],nW:0,nH:0,oW:0,oH:0};
    for(const img of images){const d=b64(img);if(d)res.images.push(d);}
    if(mainImg){res.nW=mainImg.naturalWidth||0;res.nH=mainImg.naturalHeight||0;res.oW=mainImg.offsetWidth||0;res.oH=mainImg.offsetHeight||0;}
    return res;
}"""

TASK_TEXT_JS = """() => {
    for(const s of ["span.cap-flex.cap-items-center","div[class*='captcha_verify_bar--title']","[class*='captcha_verify_bar'] span","[class*='captcha-verify'] .text"]){
        const el=document.querySelector(s);if(el&&el.textContent.trim())return el.textContent.trim();}
    return '';
}"""

DRAG_INFO_JS = """() => {
    let c = document.querySelector('.TUXModal.captcha-verify-container')
        || document.querySelector('.captcha_verify_container')
        || document.querySelector('#captcha_container');
    if(!c) return null;
    const el=c.querySelector('.cap-rounded-full > div')||c.querySelector('.secsdk-captcha-drag-icon')||c.querySelector('#captcha_slide_button')||c.querySelector('[draggable="true"]');
    if(!el)return null;
    const r=el.getBoundingClientRect(),p=el.parentElement?el.parentElement.getBoundingClientRect():r;
    return {x:r.left,y:r.top,w:r.width,h:r.height,pW:p.width,pH:p.height};
}"""

CONFIRM_JS = """() => {
    let c=document.querySelector('.TUXModal.captcha-verify-container')||document.querySelector('.captcha_verify_container');
    if(!c)return false;
    const b=c.querySelector('.TUXButton-label')||c.querySelector('.verify-captcha-submit-button')||c.querySelector('button[type="submit"]');
    if(b){b.click();return true;}return false;
}"""

SUCCESS_JS = """() => {
    const c1=document.querySelector('.TUXModal.captcha-verify-container'),c2=document.querySelector('.captcha_verify_container');
    if(!c1&&!c2)return true;
    function v(e){if(!e)return false;const s=window.getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden'&&parseFloat(s.opacity)>0.1;}
    if(!v(c1)&&!v(c2))return true;return false;
}"""

class TiktokSolver(CaptchaSolverBase):

    async def solve(self, selector: str = '') -> bool:
        self._log('Solving TikTok Captcha...')
        await random_mouse_wiggle(self.page)
        for attempt in range(self.attempts):
            self._log(f'Attempt {attempt + 1}/{self.attempts}')
            try:
                if await self._attempt(selector or self.selector):
                    self._log('TikTok Captcha solved!')
                    return True
            except Exception as e:
                self._log('Error:', e)
                if attempt < self.attempts - 1:
                    await sleep(rand(1500, 3000))
        raise RuntimeError('TikTok Captcha: failed. Error: ERROR_CAPTCHA_UNSOLVABLE')

    async def _attempt(self, sel: str) -> bool:
        page = self.page

        container_sels = sel or f'{NEW_CONTAINER}, {OLD_CONTAINER}, {FALLBACK_CONTAINERS}'
        container = await wait_for_element(page, container_sels, 10000)
        if not container:
            raise RuntimeError('TikTok: captcha container not found')

        await sleep(rand(500, 1500))

        detect = json.loads(await page.evaluate(DETECT_TYPE_JS) or '{}')
        cap_type = detect.get('type', 'unknown')
        is_old = detect.get('isOld', False)
        self._log(f'TikTok type={cap_type}, isOld={is_old}')

        if cap_type == 'unknown':
            raise RuntimeError('TikTok: unknown captcha type')

        raw_task = await page.evaluate(TASK_TEXT_JS) or ''
        self._log(f'TikTok task text: {raw_task}')

        if cap_type == 'koleso':
            text_instr = 'koleso'
        elif cap_type in ('abc', 'objects'):
            cleaned = re.sub(r'[:?\[\]\\-]', '', raw_task) if raw_task else ''
            text_instr = f'abc,{cleaned}' if cleaned else 'abc'
        else:
            text_instr = cap_type

        img_data = await page.evaluate(GET_IMAGES_JS, cap_type)
        if not img_data or not img_data.get('images'):
            raise RuntimeError('TikTok: no captcha images found')

        images = img_data['images']
        nW, nH = img_data.get('nW', 0), img_data.get('nH', 0)
        oW, oH = img_data.get('oW', 0), img_data.get('oH', 0)
        self._log(f'TikTok: {len(images)} images, natural={nW}x{nH}, offset={oW}x{oH}')

        if cap_type == 'koleso':
            if len(images) < 2:
                raise RuntimeError('TikTok koleso needs 2 images')
            raw_result = await self.client.solve_coordinates_raw(
                click='geetest',
                textinstructions='koleso',
                body0=images[0],
                body1=images[1],
                debug=self.debug,
            )
        else:
            raw_result = await self.client.solve_coordinates_raw(
                click='geetest',
                textinstructions=text_instr,
                body=images[0],
                debug=self.debug,
            )

        if not raw_result:
            raise RuntimeError('TikTok: empty API response')
        self._log(f'TikTok result: {raw_result}')

        if cap_type == 'koleso':
            return await self._handle_koleso(page, raw_result)
        elif cap_type == 'slider':
            return await self._handle_slider(page, raw_result, nH, oH, is_old)
        elif cap_type == 'pazl':
            return await self._handle_pazl(page, raw_result, nW, oW)
        else:
            return await self._handle_click(page, raw_result, nW, nH, oW, oH)

    async def _handle_koleso(self, page, raw: str) -> bool:
        parts = re.sub(r'[^0-9,]', '', raw).split(',')
        angle = int(parts[1]) if len(parts) > 1 else int(parts[0])
        self._log(f'koleso angle={angle}')

        di = await page.evaluate(DRAG_INFO_JS)
        if not di:
            raise RuntimeError('koleso: drag element not found')

        max_move = di['pW'] - di['w']
        offset = round((angle / 271) * max_move)
        sx = di['x'] + di['w'] / 2
        sy = di['y'] + di['h'] / 2

        self._log(f'koleso: offset={offset}, parentW={di["pW"]}, elW={di["w"]}')
        await self._drag(page, sx, sy, sx + offset, sy)
        await sleep(rand(2000, 3000))
        return await self._check_success(page)

    async def _handle_slider(self, page, raw: str, nH: int, oH: int, is_old: bool) -> bool:
        parts = re.sub(r'[^0-9,]', '', raw).split(',')
        res1 = int(parts[0])
        self._log(f'slider raw={res1}, nH={nH}, oH={oH}')

        if nH > 0 and oH > 0:
            res1 = round(res1 / nH * oH)
            self._log(f'slider scaled={res1}')

        dist = res1 - 5

        if is_old:
            el = await page.query_selector('.secsdk-captcha-drag-icon')
            if el:
                box = await el.bounding_box()
                if box:
                    await self._drag(page, box['x'] + box['width']/2, box['y'] + box['height']/2,
                                     box['x'] + box['width']/2 + dist, box['y'] + box['height']/2)
        else:
            di = await page.evaluate(DRAG_INFO_JS)
            if di:
                sx = di['x'] + di['w'] / 2
                sy = di['y'] + di['h'] / 2
                await self._drag(page, sx, sy, sx + dist, sy)
            else:
                raise RuntimeError('slider: drag element not found')

        await sleep(1000)
        if not is_old:
            await page.evaluate(CONFIRM_JS)
        await sleep(rand(2000, 3000))
        return await self._check_success(page)

    async def _handle_pazl(self, page, raw: str, nW: int, oW: int) -> bool:
        parts = re.sub(r'[^0-9,]', '', raw).split(',')
        res1 = int(parts[0])
        self._log(f'pazl raw={res1}, nW={nW}, oW={oW}')

        if nW > 0 and oW > 0:
            res1 = round(res1 / nW * oW)
            self._log(f'pazl scaled={res1}')

        dist = res1 - 5

        di = await page.evaluate(DRAG_INFO_JS)
        if not di:
            raise RuntimeError('pazl: drag element not found')

        sx = di['x'] + di['w'] / 2
        sy = di['y'] + di['h'] / 2
        await self._drag(page, sx, sy, sx + dist, sy)
        await sleep(1000)
        await page.evaluate(CONFIRM_JS)
        await sleep(rand(2000, 3000))
        return await self._check_success(page)

    async def _handle_click(self, page, raw: str, nW: int, nH: int, oW: int, oH: int) -> bool:
        clean = re.sub(r'[^0-9,;]', '', raw)
        groups = clean.split(';')

        img = await page.query_selector(
            '#captcha-verify-image, .TUXModal.captcha-verify-container img, '
            '.captcha_verify_container img, div[class*="captcha"][class*="verify"] img')
        if not img:
            raise RuntimeError('click: image not found')
        box = await img.bounding_box()
        if not box:
            raise RuntimeError('click: image box not found')

        for g in groups:
            p = g.split(',')
            if len(p) < 2:
                continue
            x, y = int(p[0]), int(p[1])
            if nW > 0 and oW > 0:
                x = round(x / nW * oW)
            if nH > 0 and oH > 0:
                y = round(y / nH * oH)
            self._log(f'click: ({x},{y})')
            await sleep(500)
            await page.mouse.click(box['x'] + x, box['y'] + y)
            await sleep(1200)

        await sleep(2000)
        submit = await page.query_selector(
            '.TUXButton-label, .verify-captcha-submit-button, button[type="submit"]')
        if submit:
            await submit.click()
        await sleep(rand(2000, 3000))
        return await self._check_success(page)

    async def _drag(self, page, sx, sy, ex, ey, steps=20):
        await page.mouse.move(sx, sy)
        await page.mouse.down()
        await sleep(100)
        dx = (ex - sx) / steps
        for i in range(1, steps + 1):
            await page.mouse.move(sx + dx * i + rand(-2, 2), sy + rand(-1, 1))
            await sleep(rand(30, 70))
        await page.mouse.move(ex, ey)
        await sleep(100)
        await page.mouse.up()
        await sleep(300)

    async def _check_success(self, page) -> bool:
        await sleep(1000)
        return await page.evaluate(SUCCESS_JS)

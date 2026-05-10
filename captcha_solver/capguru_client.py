from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from .helpers import sleep

class CapGuruClient:

    SERVERS = [
        'https://api2.cap.guru',
        'https://api.cap.guru',
        'https://api5.cap.guru',
        'https://api4.cap.guru',
        'https://api3.cap.guru',
        'https://ipv6.cap.guru',
    ]

    def __init__(self, api_key: str, server_url: str = 'https://api2.cap.guru') -> None:
        self.api_key = api_key
        self.server_url = server_url.rstrip('/')
        self._working_server: str = self.server_url
        self._last_task_id: Optional[str] = None

    async def _post(self, payload: dict, debug: bool = False) -> str:
        payload['key'] = self.api_key
        if 'method' not in payload:
            payload['method'] = 'post'

        servers = [self.server_url] + [s for s in self.SERVERS if s != self.server_url]
        last_err = None
        for server in servers:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f'{server}/in.php',
                        content=json.dumps(payload),
                        headers={
                            'Content-Type': 'application/json',
                            'Accept': 'application/json, text/plain, */*',
                        },
                    )
                    resp.raise_for_status()
                    text = resp.text.strip()
                    if debug:
                        print(f'[CapGuruClient] in.php ({server}):', text[:300])
                    self._working_server = server
                    return text
            except Exception as e:
                last_err = e
                if debug:
                    print(f'[CapGuruClient] server {server} failed: {e}')
        raise RuntimeError(f'Cap.Guru: all servers failed. Last error: {last_err}')

    async def _get_result(self, task_id: str, debug: bool = False) -> str:
        server = self._working_server
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f'{server}/res.php',
                    params={'action': 'get', 'key': self.api_key, 'id': task_id},
                )
                res.raise_for_status()
                text = res.text.strip()
                if debug:
                    print(f'[CapGuruClient] res.php ({server}) id={task_id}:', text[:300])
                return text
        except Exception as e:
            if debug:
                print(f'[CapGuruClient] res.php ({server}) failed: {e}')
            return await self._get_result_fallback(task_id, debug=debug)

    async def _get_result_fallback(self, task_id: str, debug: bool = False) -> str:
        """Try all servers if the primary one fails for res.php."""
        last_err = None
        for server in self.SERVERS:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(
                        f'{server}/res.php',
                        params={'action': 'get', 'key': self.api_key, 'id': task_id},
                    )
                    res.raise_for_status()
                    text = res.text.strip()
                    if debug:
                        print(f'[CapGuruClient] res.php fallback ({server}) id={task_id}:', text[:300])
                    self._working_server = server
                    return text
            except Exception as e:
                last_err = e
                if debug:
                    print(f'[CapGuruClient] res.php fallback ({server}) failed: {e}')
        raise RuntimeError(f'Cap.Guru res.php: all servers failed. Last error: {last_err}')

    async def send(self, payload: dict, debug: bool = False) -> str:
        text = await self._post(payload, debug=debug)
        if text.startswith('OK|'):
            task_id = text.split('|', 1)[1]
            self._last_task_id = task_id
            return task_id
        if 'NOT' in text:
            return 'WAIT'
        raise RuntimeError(f'Cap.Guru create task error: {text}')

    async def get(self, task_id: str, debug: bool = False) -> str:
        text = await self._get_result(task_id, debug=debug)
        if text.startswith('OK|'):
            return text.split('|', 1)[1]
        if 'NOT' in text or text == 'CAPCHA_NOT_READY':
            return 'WAIT'
        raise RuntimeError(f'Cap.Guru result error: {text}')

    async def click(self, payload: dict, debug: bool = False) -> Optional[str]:
        task_id_str = await self.send(payload, debug=debug)
        if 'ERROR' in task_id_str or 'WAIT' in task_id_str:
            return None
        task_id = task_id_str.strip()
        await sleep(5000)
        for _ in range(60):
            result = await self.get(task_id, debug=debug)
            if result == 'WAIT':
                await sleep(3000)
                continue
            if 'ERROR' in result and 'notpic' not in result:
                return None
            return result
        return None

    async def solve_recap(self, image_b64: str, task_text: str, sizex: int = 9, debug: bool = False) -> Optional[str]:
        return await self.click({
            'type': 'base64', 'click': 'recap2', 'textinstructions': task_text,
            'sizex': sizex, 'bas_disable_image_convert': '1', 'body': image_b64,
        }, debug=debug)

    async def solve_coordinates_raw(
        self,
        click: str,
        body0: Optional[str] = None,
        body1: Optional[str] = None,
        body: Optional[str] = None,
        textinstructions: Optional[str] = None,
        vernet: Optional[int] = None,
        coordinatescaptcha: str = '1',
        bas_disable_image_convert: Optional[str] = None,
        debug: bool = False,
    ) -> Optional[str]:
        payload: dict = {'type': 'base64', 'click': click}
        if body0 is not None:
            payload['body0'] = body0
        if body1 is not None:
            payload['body1'] = body1
        if body is not None:
            payload['body'] = body
        payload['coordinatescaptcha'] = coordinatescaptcha
        if textinstructions:
            payload['textinstructions'] = textinstructions
        if vernet is not None:
            payload['vernet'] = str(vernet)
        if bas_disable_image_convert:
            payload['bas_disable_image_convert'] = bas_disable_image_convert
        return await self.click(payload, debug=debug)

    def _parse_tile_indices(self, raw: str) -> list[int]:
        indices = []
        for part in re.sub(r'[^0-9,]', '', raw).split(','):
            part = part.strip()
            if part:
                try:
                    indices.append(int(part) - 1)
                except ValueError:
                    pass
        return indices

    def _parse_raw_pixel_coords(self, raw: str) -> list[int]:
        return [int(n) for n in re.findall(r'[0-9]+', raw)]

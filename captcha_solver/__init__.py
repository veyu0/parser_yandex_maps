from .helpers import (
    sleep, rand, SelectorStep, parse_selector,
    find_element, wait_for_element,
    screenshot_element, canvas_to_base64,
    human_move, human_click, random_mouse_wiggle,
)
from .capguru_client import CapGuruClient
from .base_solver import CaptchaSolverBase
from .recaptcha import RecaptchaSolver
from .other import OtherSolver
from .hcaptcha import HcaptchaSolver
from .geetest import GeetestSolver
from .funcaptcha import FuncaptchaSolver
from .tiktok import TiktokSolver
from .aws import AwsSolver

from playwright.async_api import Page

class CaptchaSolver:

    def __init__(
        self,
        page: Page,
        api_key: str,
        server: str = 'https://api.cap.guru',
        attempts: int = 5,
        debug: bool = False,
        selector: str = '',
    ) -> None:
        self._kwargs = dict(
            page=page, api_key=api_key, server=server,
            attempts=attempts, debug=debug, selector=selector,
        )
        self.page = page
        self.api_key = api_key
        self.server = server
        self.attempts = attempts
        self.debug = debug
        self.selector = selector
        self.client = CapGuruClient(api_key, server)

    def _make(self, cls):
        return cls(**self._kwargs)

    async def solve_recaptcha2(self) -> bool:
        return await self._make(RecaptchaSolver).solve()

    async def solve_other(self, selector: str = '') -> bool:
        return await self._make(OtherSolver).solve(selector)

    async def solve_hcaptcha(self, selector: str = '') -> bool:
        return await self._make(HcaptchaSolver).solve(selector)

    async def solve_geetest(self, selector: str = '') -> bool:
        return await self._make(GeetestSolver).solve(selector)

    async def solve_funcaptcha(self, selector: str = '') -> bool:
        return await self._make(FuncaptchaSolver).solve(selector)

    async def solve_tiktok(self, selector: str = '') -> bool:
        return await self._make(TiktokSolver).solve(selector)

    async def solve_aws(self) -> bool:
        return await self._make(AwsSolver).solve()

__all__ = [

    'CaptchaSolver',

    'RecaptchaSolver',
    'OtherSolver',
    'HcaptchaSolver',
    'GeetestSolver',
    'FuncaptchaSolver',
    'TiktokSolver',
    'AwsSolver',

    'CapGuruClient',
    'CaptchaSolverBase',

    'sleep', 'rand', 'SelectorStep', 'parse_selector',
    'find_element', 'wait_for_element',
    'screenshot_element', 'canvas_to_base64',
    'human_move', 'human_click', 'random_mouse_wiggle',
]

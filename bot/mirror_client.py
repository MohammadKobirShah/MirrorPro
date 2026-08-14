import aiohttp


class MirrorClient:
    def __init__(self, server_url: str, api_key: str = ""):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            # BUG FIX #3: timeout যোগ করা হয়েছে
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def mirror(self, url: str, filename: str | None = None, ttl: int | None = None) -> dict:
        body = {"url": url}
        if filename:
            body["filename"] = filename
        if ttl is not None:
            body["ttl"] = ttl
        s = await self._get_session()
        async with s.post(f"{self.server_url}/api/mirror", json=body) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise Exception(data.get("detail", "mirror failed"))
            return data

    async def status(self, gid: str) -> dict:
        s = await self._get_session()
        async with s.get(f"{self.server_url}/api/status/{gid}") as resp:
            data = await resp.json()
            if resp.status != 200:
                raise Exception(data.get("detail", "status failed"))
            return data

    async def list_tasks(self) -> dict:
        s = await self._get_session()
        async with s.get(f"{self.server_url}/api/list") as resp:
            return await resp.json()

    async def delete(self, gid: str) -> dict:
        s = await self._get_session()
        async with s.delete(f"{self.server_url}/api/delete/{gid}") as resp:
            return await resp.json()

    async def health(self) -> dict:
        s = await self._get_session()
        async with s.get(f"{self.server_url}/health") as resp:
            return await resp.json()

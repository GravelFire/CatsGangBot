import asyncio
import random
from urllib.parse import unquote
import uuid

import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from datetime import datetime, timezone, timedelta
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions import account
from pyrogram.raw.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings
from .agents import generate_random_user_agent
from bot.config import settings
from typing import Callable
import functools
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers


def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
    return wrapper

class Tapper:
    def __init__(self, tg_client: Client, proxy: str):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.proxy = proxy
        self.tg_web_data = None
        self.tg_client_id = 0
        
    async def get_tg_web_data(self, ref_id) -> str:
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme="socks5",
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('catsgang_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 3)
            
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="join"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0])

            me = await self.tg_client.get_me()
            self.tg_client_id = me.id
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
            with open('data.txt', 'a') as f:
                f.write(f"{tg_web_data}\n")
            return ref_id, tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        response = await http_client.request(method, url or f"https://api.catshouse.club{endpoint or ''}", **kwargs)
        response.raise_for_status()
        return await response.json()
    
    @error_handler
    async def login(self, http_client, ref_id, global_refer, refer_lock):

        user = await self.make_request(http_client, 'GET', endpoint="/user")
        if not user:
            logger.info(f"{self.session_name} | User not found. Registering...")

            await self.make_request(http_client, 'POST', endpoint=f"/user/create?referral_code={ref_id}")
            async with refer_lock:
                if ref_id in global_refer:
                    global_refer[ref_id] += 1
            await asyncio.sleep(2)
            return await self.login(http_client, ref_id, global_refer, refer_lock)
        return user
    
    @error_handler
    async def send_cats(self, http_client):
        avatar_info = await self.make_request(http_client, 'GET', endpoint="/user/avatar")
        if avatar_info:
            attempt_time_str = avatar_info.get('attemptTime', None)
            if not attempt_time_str:
                time_difference = timedelta(hours=25)
            else:
                attempt_time = datetime.fromisoformat(attempt_time_str.replace('Z', '+00:00'))
                current_time = datetime.now(timezone.utc)
                next_day_3am = (attempt_time + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
                
                if current_time >= next_day_3am:
                    time_difference = timedelta(hours=25)
                else:
                    time_difference = next_day_3am - current_time

            if time_difference > timedelta(hours=24):
                response = await http_client.get(f"https://cataas.com/cat?timestamp={int(datetime.now().timestamp() * 1000)}", headers={
                    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "accept-language": "en-US,en;q=0.9,ru;q=0.8",
                    "sec-ch-ua": "\"Not;A=Brand\";v=\"24\", \"Chromium\";v=\"128\"",
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": "\"macOS\"",
                    "sec-fetch-dest": "image",
                    "sec-fetch-mode": "no-cors",
                    "sec-fetch-site": "cross-site"
                })
                if not response and response.status not in [200, 201]:
                    logger.error(f"{self.session_name} | Failed to fetch image from cataas.com")
                    return None
                
                image_content = await response.read()
                    
                boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
                form_data = (
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="photo"; filename="{uuid.uuid4().hex}.jpg"\r\n'
                    f'Content-Type: image/jpeg\r\n\r\n'
                ).encode('utf-8')
                
                form_data += image_content
                form_data += f'\r\n--{boundary}--\r\n'.encode('utf-8')
                
                headers = http_client.headers.copy()
                headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
                response = await self.make_request(http_client, 'POST', endpoint="/user/avatar/upgrade", data=form_data, headers=headers)
                if response:
                    return response.get('rewards', 0)
                else:
                    return None
            else:
                hours, remainder = divmod(time_difference.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f"{self.session_name} | Time until next avatar upload: <y>{hours}</y> hours, <y>{minutes}</y> minutes, and <y>{seconds}</y> seconds")
                return None
    
    @error_handler
    async def join_and_mute_tg_channel(self, link: str):
        await asyncio.sleep(delay=random.randint(15, 30))
        
        if not self.tg_client.is_connected:
            await self.tg_client.connect()
            
        parsed_link = link if 'https://t.me/+' in link else link[13:]
        try:
            try:
                chat = await self.tg_client.join_chat(parsed_link)
                logger.info(f"{self.session_name} | Successfully joined chat <y>{chat.title}</y>")
            except Exception as join_error:
                if "USER_ALREADY_PARTICIPANT" in str(join_error):
                    logger.info(f"{self.session_name} | Already a member of the chat: {link}")
                    chat = await self.tg_client.get_chat(parsed_link)
                else:
                    
                    raise join_error

            chat_id = chat.id
            chat_title = getattr(chat, 'title', link)

            await asyncio.sleep(random.randint(5, 10))

            peer = await self.tg_client.resolve_peer(chat_id)
            await self.tg_client.invoke(account.UpdateNotifySettings(
                peer=InputNotifyPeer(peer=peer),
                settings=InputPeerNotifySettings(mute_until=2147483647)
            ))
            logger.info(f"{self.session_name} | Successfully muted chat <y>{chat_title}</y>")

        except Exception as e:
            logger.error(f"{self.session_name} | Error joining/muting channel {link}: {str(e)}")

        finally:
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

        await asyncio.sleep(random.randint(10, 20))
    
    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/user", data={'group': 'cats'})
    
    @error_handler
    async def done_tasks(self, http_client, task_id, type_):
        return await self.make_request(http_client, 'POST', endpoint=f"/tasks/{task_id}/{type_}", json={})
    
    
    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        ip = response.get('origin', 'Site is not available')
        logger.info(f"{self.session_name} | Proxy IP: {ip}")
    
    @error_handler
    async def run(self, ref_id,global_refer, refer_lock) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
                random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
                logger.info(f"{self.session_name} | Bot will start in <y>{random_delay}s</y>")
                await asyncio.sleep(random_delay)
                
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
        
        ref_id, init_data = await self.get_tg_web_data(ref_id)
        if not init_data:
            if not http_client.closed:
                await http_client.close()
            if proxy_conn:
                if not proxy_conn.closed:
                    proxy_conn.close()

        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

        while True:
            try:
                if http_client.closed:
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
                    if settings.FAKE_USERAGENT:            
                        http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')
                
                http_client.headers['Authorization'] = f"tma {init_data}"
                
                user = await self.login(http_client=http_client, ref_id=ref_id, global_refer=global_refer, refer_lock=refer_lock)
                if not user:
                    logger.error(f"{self.session_name} | Failed to login")
                    await http_client.close()
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()
                    continue
                
                logger.info(f"{self.session_name} | <y>Successfully logged in</y>")
                logger.info(f"{self.session_name} | User ID: <y>{user.get('id')}</y> | Telegram Age: <y>{user.get('telegramAge')}</y> | Points: <y>{user.get('totalRewards')}</y>|referrerCode: <y>{user.get('referrerCode')}</y>")
                if user.get('referrerCode') is not None and user.get('referrerCode') not in global_refer:
                    global_refer[user.get('referrerCode')] = 0
                data_task = await self.get_tasks(http_client=http_client)
                if data_task is not None and data_task.get('tasks', {}):
                    for task in data_task.get('tasks'):
                        if task['completed'] is True:
                            continue
                        id = task.get('id')
                        type = task.get('type')
                        title = task.get('title')
                        reward = task.get('rewardPoints')
                        type_=('check' if type == 'SUBSCRIBE_TO_CHANNEL' else 'complete')
                        #if type_ == 'check':
                        #    await self.join_and_mute_tg_channel(link=task.get('params').get('channelUrl'))
                        #    await asyncio.sleep(2)
                        done_task = await self.done_tasks(http_client=http_client, task_id=id, type_=type_)
                        if done_task and (done_task.get('success', False) or done_task.get('completed', False)):
                            logger.info(f"{self.session_name} | Task <y>{title}</y> done! Reward: {reward}")
                                
                else:
                    logger.error(f"{self.session_name} | No tasks")
                
                reward = await self.send_cats(http_client=http_client)
                if reward:
                    logger.info(f"{self.session_name} | Reward from Avatar quest: <y>{reward}</y>")
                
                
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()
            
            except InvalidSession as error:
                raise error

            except Exception as error:
                logger.error(f"{self.session_name} | Unknown error: {error}")
                await asyncio.sleep(delay=3)
            finally:
                with open('refer.txt', 'w') as f:
                    f.write('\n'.join(global_refer.keys()))
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()  
                        
            sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
            logger.info(f"{self.session_name} | Sleep <y>{sleep_time}s</y>")
            await asyncio.sleep(delay=sleep_time)
            
            
            
            

async def run_tapper(tg_client: Client, proxy: str | None, global_refer, refer_lock):
    # use  refer_lock sync access to  global_refer
    async with refer_lock:
        
        ref_id = next(iter(global_refer))  # 
        if global_refer[ref_id] > 9:
            del global_refer[ref_id]  #  10 refer  every account

    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run(ref_id=ref_id,global_refer=global_refer, refer_lock=refer_lock)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")

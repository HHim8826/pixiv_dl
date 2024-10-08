# -*- coding: utf-8 -*
import asyncio
import math
import os
import platform
import time

import aiofiles
import aiohttp
import requests
import toml
from tqdm import tqdm

if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

banner = """  _                                                       
 |_)  o      o           /\    _      ._    _     ._      
 |    |  ><  |  \/      /--\  _>  \/  | |  (_  o  |_)  \/ 
                    __            /               |    /  
"""


def get_config() -> dict:
    cfg = toml.load(os.path.expanduser('./pyproject.toml'))
    return cfg


async def premium_page(url, headers, params, session, id_list) -> list:
    async with session.get(url, headers=headers, params=params) as aioreq:
        data = await aioreq.json()
        json_data = data['body']['illustManga']['data']
        for data_info in json_data:
            id_list.append(data_info['id'])
    return id_list


async def premium_search(
    name: str, order_num: int, mode_num: int, page_num: int, cfg: dict, only_illust=True
) -> list:
    headers = {
        'referer': 'https://www.pixiv.net/',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
        'Content-Type': 'application/json',
    }
    url = f'https://www.pixiv.net/ajax/search/artworks/{name}'
    order = ['popular_d', 'popular_male_d', 'popular_female_d']
    mode = ['s_tag', 'safe', 'r18']
    tasks = []
    id_list = []

    order_ = order[order_num]
    mode_ = mode[mode_num]

    async with aiohttp.ClientSession() as session:
        for pages in range(1, page_num + 1):
            params = {
                'word': name,
                'order': order_,
                'mode': mode_,
                's_mode': 's_tag',
            }

            if only_illust:
                params['type'] = 'illust_and_ugoira'
            else:
                params['type'] = 'all'

            params['p'] = pages

            tasks.append(asyncio.create_task(premium_page(url, headers, params, session, id_list)))

        id_list = await asyncio.wait(tasks)

        for val in id_list[0]:
            id_list = val.result()

    return id_list


def pixiv_search(name: str, cfg: dict, mode=0) -> iter:
    headers = {
        'referer': 'https://www.pixiv.net/',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
    }

    url = f'https://www.pixiv.net/ajax/search/illustrations/{name}'

    params = {'word': name}

    if mode == 0:
        params['mode'] = 'all'
    elif mode == 1:
        params['mode'] = 'safe'
    elif mode == 2:
        params['mode'] = 'r18'

    req = requests.get(url, headers=headers, params=params)
    req = req.json()

    try:
        # get id
        body_data = req['body']['illust']['data']
        for info in body_data:
            id_num = info['id']
            yield id_num

    except KeyError:
        body_data = req['body']['popular']['permanent']

        for info in body_data:
            id_num = info['id']
            yield id_num

        body_data_1 = req['body']['popular']['recent']
        for info_2 in body_data_1:
            id_num_2 = info_2['id']
            yield id_num_2


def get_user_illusts(user_id, cfg: dict) -> iter:
    headers = {
        'referer': 'https://www.pixiv.net/ranking.php',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
        'Content-Type': 'application/json',
    }
    url = f'https://www.pixiv.net/ajax/user/{user_id}/profile/all'

    req = requests.get(url, headers=headers)
    req = req.json()
    for illusts_ids in req['body']['illusts']:
        yield illusts_ids


async def get_page_info(id_list, url, headers, payload, session):
    async with session.get(url, headers=headers, params=payload) as aioreq:
        data = await aioreq.json()
        json_data = data['body']['illust']['data']

        for id_ in json_data:
            try:
                id_list.append(id_['id'])
            except KeyError:
                pass
    return id_list


async def get_id_info(id_, headers, session, bookmark, dl_list):
    illust_url = f'https://www.pixiv.net/ajax/illust/{id_}'
    async with session.get(illust_url, headers=headers) as aioreq:
        data = await aioreq.json()
        json_data = data['body']
        if json_data['bookmarkCount'] > bookmark:
            i_id = json_data['urls']['original'].split('/')[-1].split('_')[0]
            dl_list.append(i_id)

    return dl_list


async def popular_search(search_name: str, bookmark: int, cfg: dict, page=50, mode=0) -> list:
    headers = {
        'referer': 'https://www.pixiv.net',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
        'Content-Type': 'application/json',
    }
    url = f'https://www.pixiv.net/ajax/search/illustrations/{search_name}'
    tasks = []
    id_list = []
    dl_list = []

    payload = {'word': search_name, 'p': 1, 's_mode': 's_tag', 'type': 'illust_and_ugoira'}

    if mode == 0:
        payload['mode'] = 'all'
    elif mode == 1:
        payload['mode'] = 'safe'
    elif mode == 2:
        payload['mode'] = 'r18'

    req_data = requests.get(url, params=payload, headers=headers).json()
    # print(req_data)
    total_illust = req_data['body']['illust']['total']
    max_page = math.ceil(total_illust / 60)

    if page > max_page:
        page = max_page

    async with aiohttp.ClientSession() as session:
        for page_num in range(1, page + 1):
            payload = {'word': search_name, 'p': 1, 's_mode': 's_tag', 'type': 'illust_and_ugoira'}

            if mode == 0:
                payload['mode'] = 'all'
            elif mode == 1:
                payload['mode'] = 'safe'
            elif mode == 2:
                payload['mode'] = 'r18'

            payload['p'] = page_num

            tasks.append(
                asyncio.create_task(get_page_info(id_list, url, headers, payload, session))
            )

        print(f'正在獲得前{page}頁的作品. . .')
        id_list = await asyncio.wait(tasks)

        for val in id_list[0]:
            id_list = val.result()

        for id_ in id_list:
            tasks.append(asyncio.create_task(get_id_info(id_, headers, session, bookmark, dl_list)))

        print(f'正在獲得所有作品({len(id_list)}件)的點讚量. . .')
        dl_list = await asyncio.wait(tasks)

        for i in dl_list[0]:
            dl_list = i.result()

        print(f'正在下載超過{bookmark}點讚的作品,共({len(dl_list)}件)作品. . .')
        return dl_list


async def ranking_info(url, headers, payload, session) -> dict:
    async with session.get(url, headers=headers, params=payload) as aioreq:
        data = await aioreq.json()
        return data


async def ranking(page: int, cfg: dict, mode_num=0, r18mode=0, only_illust=False) -> list:
    headers = {
        'referer': 'https://www.pixiv.net/ranking.php',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
        'Content-Type': 'application/json',
    }
    url = 'https://www.pixiv.net/ranking.php'
    id_list = []
    tasks = []

    if mode_num == 0:
        mode = 'daily'
    elif mode_num == 1:
        mode = 'weekly'
    elif mode_num == 2:
        mode = 'monthly'
    elif mode_num == 3:
        mode = 'rookie'
    elif mode_num == 4:
        mode = 'original'
    elif mode_num == 5:
        mode = 'female'
    elif mode_num == 6:
        if r18mode == 0:
            mode = 'daily_r18'
        elif r18mode == 1:
            mode = 'weekly_r18'
        elif r18mode == 2:
            mode = 'male_r18'
        elif r18mode == 3:
            mode = 'female_r18'
    elif mode_num == 7:
        mode = 'male'

    async with aiohttp.ClientSession() as session:
        for page_num in range(page):
            params = {'format': 'json', 'mode': mode}

            if mode == 'daily' or 'weekly' or 'monthly' or 'rookie' and only_illust:
                params['content'] = 'illust'

            params['p'] = page_num + 1

            tasks.append(asyncio.create_task(ranking_info(url, headers, params, session)))

        ids = await asyncio.wait(tasks)

        for id_ in ids[0]:
            result_data = id_.result()
            json_data = result_data['contents']
            for data_info in json_data:
                id_num = data_info['illust_id']
                id_list.append(id_num)

    return id_list


async def pixiv_get(id, cfg: dict, session) -> dict:
    url = f'https://www.pixiv.net/ajax/illust/{id}/pages'
    headers = {
        'referer': 'https://www.pixiv.net/',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
    }
    async with session.get(url, headers=headers) as req:
        data = await req.json()
        return data['body']


async def dl_img(id, cfg: dict, session, pbar) -> None:
    headers = {
        'referer': 'https://www.pixiv.net/',
        'cookie': cfg['login']['cookie'],
        'user-agent': cfg['login']['user-agent'],
    }
    data = await pixiv_get(id, cfg, session)
    for data_info in data:
        img_url = data_info['urls']['original']
        name = img_url.split('/')[-1]
        async with session.get(img_url, headers=headers) as req:
            async with aiofiles.open(f'./img/{name}', 'wb') as aiof:
                await aiof.write(await req.content.read())
    pbar.update(1)


async def main():
    os.system('cls')
    print(banner)
    cfg = get_config()
    print(
        """
        0:Pixiv_id mode
        1:Search mode
        2:Ranking mode
        3:User illusts
        4:Premium search(Need premium)
        5:popular search(non premium)
        """
    )
    mode = int(input('Mode:'))
    print(f'Mode:{mode}'.center(50, '='))

    id_list = []
    tasks = []

    if mode == 0:
        id_list.append(int(input('Pixiv_id:')))
    elif mode == 1:
        search = input('Search:')
        print(''.center(50, '='))
        print('0:All\n1:Safe\n2:R18(login)')
        mode_num = int(input('mode:'))
        print(''.center(50, '='))
        ids = pixiv_search(search, cfg, mode=mode_num)
        id_list = [id for id in ids]

    elif mode == 2:
        print(
            """
            0:daily
            1:weekly
            2:monthly
            3:rookie
            4:original
            5:for female
            6:r18(login)
            7:for male
            """
        )
        ranking_num = int(input('ranking_mode:'))
        print(''.center(50, '='))
        page = int(input('Page:'))
        print(''.center(50, '='))

        if ranking_num in {0, 1, 2, 3}:
            on_illust = input('Only illustration[y/n]:')
            if on_illust == 'y':
                ids = await ranking(page, cfg, mode_num=ranking_num, only_illust=True)
                print(''.center(50, '='))
            else:
                ids = await ranking(page, cfg, mode_num=ranking_num)
        elif ranking_num == 6:
            print('0:daily_r18\n1:weekly_r18\n2:male_r18\n3:female_r18')
            r18mode = int(input('R18_mode:'))
            print(''.center(50, '='))
            ids = await ranking(page, cfg, mode_num=ranking_num, r18mode=r18mode)
        else:
            ids = await ranking(page, cfg, mode_num=ranking_num)

        id_list = ids

    elif mode == 3:
        user_id = int(input('user_id:'))
        print(''.center(50, '='))
        ids = get_user_illusts(user_id, cfg)
        id_list = [id for id in ids]

    elif mode == 4:
        search = input('Search:')
        print(''.center(50, '='))
        print('0:All popular\n1:Popula for male\n2:Popula for female')
        order_num = int(input('order:'))
        print(''.center(50, '='))
        print('0:r18 & safe\n1:safe\n2:R18')
        mode_4_num = int(input('mode:'))
        print(''.center(50, '='))
        pages = int(input('pages:'))
        print(''.center(50, '='))
        only_illust = input('only_illust[y/n]:')
        print(''.center(50, '='))
        if only_illust == 'n':
            id_list = await premium_search(
                search, order_num, mode_4_num, pages, cfg, only_illust=False
            )
        else:
            id_list = await premium_search(search, order_num, mode_4_num, pages, cfg)

    elif mode == 5:
        search = input('Search:')
        print(''.center(50, '='))
        collection = int(input('collection:'))
        print(''.center(50, '='))
        print('0:All(login)\n1:Safe(login)\n2:R18(login)')
        r18mode = int(input('Mode:'))
        st_time = time.time()
        id_list = await popular_search(search, collection, cfg, mode=r18mode)

    try:
        if mode != 5:
            st_time = time.time()
        with tqdm(total=len(id_list)) as pbar:
            async with aiohttp.ClientSession() as session:
                for id in id_list:
                    tasks.append(asyncio.create_task(dl_img(id, cfg, session, pbar)))
                await asyncio.wait(tasks)
        print(f'總用時:{round(time.time() - st_time)}sec'.center(47, '='))
    except ValueError:
        pass


if __name__ == '__main__':
    asyncio.run(main())

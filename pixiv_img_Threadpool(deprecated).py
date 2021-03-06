#-*- coding: utf-8 -*
import os
import requests
import toml
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor,as_completed

banner = '''  _                                                       
 |_)  o      o           /\    _      ._    _     ._      
 |    |  ><  |  \/      /--\  _>  \/  | |  (_  o  |_)  \/ 
                    __            /               |    /  
'''

def get_config():
    cfg = toml.load(os.path.expanduser('./pixiv_cookie.toml'))
    return cfg

def premium_search(name:str,order_num:int,mode_num:int,page_num:int,cfg:dict):
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    
    order = ['popular_d','popular_male_d','popular_female_d']
    mode = ['s_tag','safe','r18']
    
    for pages in range(page_num):   
        
        params = {
            'word' : {name},
            'order' : {order[order_num]},
            'mode' : {mode[mode_num]},
            'p' : {pages+1},
            's_mode' : 's_tag',
            'type' : 'all'
        }
        
        url = f'https://www.pixiv.net/ajax/search/artworks/{name}'
        req = requests.get(url,headers=headers,params=params)
        
        json_data = req.json()
        target_data = json_data['body']['illustManga']['data']
        
        for data_info in target_data:
            illusts_id = data_info["id"]
            yield illusts_id

def pixiv_search(name:str,cfg:dict,mode=0) -> list:
    
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    url = f'https://www.pixiv.net/ajax/search/illustrations/{name}'
    
    if mode == 0:
        params = {
            'word' : name,
            'mode' : 'all'
        }
    elif mode == 1:
        params = {
            'word' : name,
            'mode' : 'safe'
        }
    elif mode == 2:
        params = {
            'word' : name,
            'mode' : 'r18'
        }
    
    req = requests.get(url,headers=headers,params=params)
    # q= req
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

def get_user_illusts(user_id,cfg:dict):
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    url = f'https://www.pixiv.net/ajax/user/{user_id}/profile/all'

    req = requests.get(url,headers=headers)
    req = req.json()
    for illusts_ids in req['body']['illusts']:   
        yield illusts_ids

def ranking(page:int, cfg:dict,mode_num=0,r18mode=0):
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    url = f'https://www.pixiv.net/ranking.php'
    
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
    
    

    for page_num in range(page):
        params = {
            'p' : page_num+1,
            'format' : 'json',
            'mode' : mode
        }
        
        req = requests.get(url,headers=headers,params=params)
        data = req.json()
        json_data = data['contents']
        for data_info in json_data:
            id_num = data_info['illust_id']
            yield id_num


def pixiv_get(id,cfg:dict):
    url = f'https://www.pixiv.net/ajax/illust/{id}/pages'
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    req = requests.get(url,headers=headers)
    data = req.json()
    return data['body']

def dl_img(id,cfg:dict):
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    data = pixiv_get(id,cfg)
    for data_info in data:
        img_url = data_info['urls']['original']
        name = img_url.split('/')[-1]
        req = requests.get(img_url,headers=headers)
        with open(f'./img/{name}','wb') as f:
            f.write(req.content)

def main():

    print(banner)
    cfg = get_config()
    print('0:Pixiv_id mode\n1:Search mode\n2:Ranking mode\n3:User illusts\n4:Premium search(Need premium)')
    mode = int(input('Mode:'))
    print(f"Mode:{mode}".center(50,'='))
     
    id_list = []
    tasks = []
    
    if mode == 0:
        dl_img(int(input('Pixiv_id:')),cfg) 
            
    elif mode == 1:
        search = input("Search:")
        print("".center(50,'='))
        print('0:All\n1:Safe\n2:R18(login)')
        mode_num = int(input('mode:'))
        print("".center(50,'='))
        ids = pixiv_search(search,cfg,mode=mode_num)
        id_list = [id for id in ids]
        
    elif mode == 2:
        print('0:daily\n1:weekly\n2:monthly\n3:rookie\n4:original\n5:for female\n6:r18(login)\n7:for male')     
        ranking_num = int(input('ranking_mode:'))
        print("".center(50,'='))
        page = int(input('Page:'))
        print("".center(50,'='))
        if ranking_num == 6:
            print('0:daily_r18\n1:weekly_r18\n2:male_r18\n3:female_r18')
            r18mode = int(input("R18_mode:"))
            print("".center(50,'='))
            ids = ranking(page,cfg,mode_num=ranking_num,r18mode=r18mode)
        else:
            ids = ranking(page,cfg,mode_num=ranking_num)
            
        id_list = [id for id in ids]
        
    elif mode == 3:
        user_id = int(input('user_id:'))
        print("".center(50,'='))
        ids = get_user_illusts(user_id,cfg)
        id_list = [id for id in ids]
    
    elif mode == 4:
        search = input("Search:")
        print("".center(50,'='))
        print('0:All popular\n1:Popula for male\n2:Popula for female')
        order_num = int(input('order:'))
        print("".center(50,'='))
        print('0:r18 & safe\n1:safe\n2:R18')
        mode_4_num = int(input('mode:'))
        print("".center(50,'='))
        pages = int(input('pages:'))
        print("".center(50,'='))
        ids = premium_search(search,order_num,mode_4_num,pages,cfg)
        id_list = [id for id in ids]
    
    with ThreadPoolExecutor(50) as th:
        _th = []
        st_time = time.time()
        for ids in id_list:
            sub = th.submit(dl_img,ids,cfg)
            _th.append(sub)
            
        for ths in tqdm(as_completed(_th),total=len(_th)):
            pass

        print(f'?????????:{round(time.time() - st_time)}sec'.center(50,'='))
       
    
    # try:
    #     for id in id_list:
    #         tasks.append(asyncio.create_task(dl_img(id,cfg)))
    #     await asyncio.wait(tasks)
    # except ValueError:
    #     pass
    

if __name__ == "__main__":
    # with ThreadPoolExecutor(50) as th:
    #     th.submit(asyncio.run,main())
    main()

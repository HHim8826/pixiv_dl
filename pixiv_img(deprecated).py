banner = '''                                                                                                                           
  ___   _         _               _                                  
 | _ \ (_) __ __ (_) __ __       (_)  _ __    __ _       _ __   _  _ 
 |  _/ | | \ \ / | | \ V /       | | | '  \  / _` |  _  | '_ \ | || |
 |_|   |_| /_\_\ |_|  \_/   ___  |_| |_|_|_| \__, | (_) | .__/  \_, |
                           |___|             |___/      |_|     |__/ 
'''


#-*- coding: utf-8 -*
import requests
import os
import re
import toml
from tqdm import tqdm
from json.decoder import JSONDecodeError

# get pixiv_cookie.toml
def config_pixiv():
    cfg = toml.load(os.path.expanduser('./pixiv_cookie.toml'))       
    return cfg

def name_replace(str):
    str = str.replace(r"\u0027",'')
    str = str.replace(r'\\',"")
    str = str.replace(r"/",'')
    str = str.replace(r":",'')
    str = str.replace(r"*",'')
    str = str.replace(r"?",'')
    str = str.replace(r'"','')
    str = str.replace(r"<",'')
    str = str.replace(r">",'')
    str = str.replace(r"|",'')
    return str

# mark folder
def mark_dir(name:str,search=None,ranking=None,r18mode=False):
    if ranking == 'daily':
        mode = 'daily'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'weekly':
        mode = 'weekly'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'monthly':
        mode = 'monthly'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'rookie':
        mode = 'rookie'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'original':
        mode = 'original'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'female':
        mode = 'female'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif ranking == 'daily_r18':
        if r18mode == True:
            mode = 'daily_r18'
            path = f'./img/R18/{name}的作品'
            try:
                os.makedirs(path)
            except FileExistsError:
                pass
    elif ranking == 'male':
        mode = 'male'
        path = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass    
    elif search == None:   
        path = f'./img/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    elif search != None and isinstance(search,str):
        path = f'./img/{search}/{name}的作品'
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
    

# get json data
def pixiv_get(id,cfg:dict) -> str:
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    url = f'https://www.pixiv.net/ajax/illust/{id}/pages'
    
    req = requests.get(url,headers=headers)
    req = req.json()
    # print(req)
    body_data = req['body']
    
    return body_data

# download img
def dl_img(id:int or list,cfg:dict,search=None,ranking=None,r18mode=False,AllInOneDir=False) -> bytes:
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    # 判斷 id 是否列表
    if type(id) == list:
        for i in tqdm(id):
            # get json data
            data_json = pixiv_get(i[0],cfg)
            if AllInOneDir == True:
                    for url in data_json:
                        url = url['urls']['original']
                        re_name = url.split("/")[-1]
                        # req = th.submit(requests.get,url,headers=headers)
                        req = requests.get(url,headers=headers)
                        with open(f'./img/{re_name}','wb') as f:
                                    f.write(req.content)
            else:
                # get folder name
                folder_name = i[1]
                # mark folder
                if search != None:
                    mark_dir(folder_name,search)
                elif ranking != None:
                    if r18mode == True:
                        mark_dir(folder_name,ranking=ranking,r18mode=True)
                    else:
                        mark_dir(folder_name,ranking=ranking) 
                elif search == None:
                     mark_dir(folder_name)
                for iter1 in data_json:
                    # get original url
                    iter1 = iter1['urls']['original']
                    # get file name
                    n_name = iter1.split("/")
                    req = requests.get(iter1,headers=headers)               
                    # save img
                    if search != None:
                        with open(f'./img/{search}/{folder_name}的作品/{n_name[-1]}','wb') as f:
                            f.write(req.content)
                    elif ranking != None:
                        if r18mode == True:
                            with open(f'./img/R18/{folder_name}的作品/{n_name[-1]}','wb') as f:
                                f.write(req.content)
                        else:
                            with open(f'./img/{ranking}/{folder_name}的作品/{n_name[-1]}','wb') as f:
                                f.write(req.content)
                    elif search == None:
                        with open(f'./img/{folder_name}的作品/{n_name[-1]}','wb') as f:
                            f.write(req.content)                 
        return 'DONE'
            
    folder_name = get_user(id)         
    data_json = pixiv_get(id,cfg)
    for i in tqdm(data_json):
        i = i['urls']['original']
        n_name = i.split("/")
        if AllInOneDir == True:
            req = requests.get(i,headers=headers)
            with open(f'./img/{n_name[-1]}','wb') as f:
                f.write(req.content)
        else:
            mark_dir(folder_name)
            req = requests.get(i,headers=headers)
            
            
            with open(f'./img/{folder_name}的作品/{n_name[-1]}','wb') as f:
                f.write(req.content)
    return 'DONE'

# get id list
def pixiv_search(name:str,cfg:dict,mode=0) -> list:
    # cookie == None ?
    class_json = ['illust','popular']   
    
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    # save data
    id_list = []
    # https://www.pixiv.net/ajax/search/illustrations/甘雨(原神)?word=甘雨(原神)&order=date_d&mode=all&p=1&s_mode=s_tag_full&type=illust_and_ugoira&lang=zh_tw
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
    
    # with open("pixiv/jsondata.json",'w') as f:
    #     f.write(q.text.encode().decode('unicode_escape').replace(r'\/',r'/'))     
    # print(req,url)   
    for json_tage in class_json:
        try:
            # get id
    
            body_data = req['body']['illust']['data']
            data_long = len(body_data)
            for i in range(data_long):
                id_num = body_data[i]['id']
                userName = body_data[i]['userName'] 
                          
                userName = name_replace(userName)
                id_list.append([id_num,userName])
                          
        except KeyError:

            # print(json_tage)
            
            body_data = req['body']['popular']['permanent']
            
            id_long = len(body_data)
            # print(id_long)
            for num in range(id_long): 
                id_num = body_data[num]['id']
                userName = body_data[num]['userName']

                userName = name_replace(userName)
                id_list.append([id_num,userName])
            
                     
            body_data_1 = req['body']['popular']['recent']
            id_long_2 = len(body_data_1)
            # print(id_long_2)
            for num_2 in range(id_long_2):
                id_num_2 = body_data_1[num_2]['id']
                userName_2 = body_data_1[num_2]['userName'] 

                userName_2 = name_replace(userName_2)
                id_list.append([id_num_2,userName_2])    
    search = name
    return id_list,search

# ['daily','weekly','monthly','rookie','original','female','daily_r18','male']
def ranking(page:int, cfg:dict,mode_num=0,r18mode=0):
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    id_name_list = []
 
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
        
        # ?p={page_num+1}&format=json
        url = f'https://www.pixiv.net/ranking.php'
        
        params = {
            'p' : page_num+1,
            'format' : 'json',
            'mode' : mode
        }
        req = requests.get(url ,headers=headers,params=params)
        req = req.json()
        
        json_data = req['contents']
        times = len(json_data)
        for len_data in range(times):
            id_num = json_data[len_data]['illust_id']
            userName = json_data[len_data]['user_name']
            
            userName = name_replace(userName)
            id_name_list.append([id_num,userName])
            # id_name_list.append(id_num)
    
    if mode_num == 6:
        mode = 'daily_r18'
    return id_name_list,mode
           
# https://www.pixiv.net/ajax/search/artworks/甘雨?word=甘雨&order=popular_d&mode=all&p=1&s_mode=s_tag&type=all
#Need premium 
def premium_search(name:str,order_num:int,mode_num:int,page_num:int,cfg:dict):
    id_list = []
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
        print(json_data)
        data_long = len(json_data['body']['illustManga']['data'])
        target_data = json_data['body']['illustManga']['data']
        
        for list_num in range(data_long):
            # print(target_data[0])
            # print(data_long)
            illusts_id = target_data[list_num]["id"]
            
            user_name = target_data[list_num]['userName']
            userName = name_replace(userName)
                    
            id_list.append([illusts_id,user_name])
       
    search = name        
    return id_list,search


def get_user_illusts(user_id:int,cfg:dict):
    id_list = []
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    url = f'https://www.pixiv.net/ajax/user/{user_id}/profile/all'
    user_url = f'https://www.pixiv.net/ajax/user/{user_id}'
    
    req_user = requests.get(user_url,headers=headers)
    req_user = req_user.json()
    user_name = req_user['body']['name']

    req = requests.get(url,headers=headers)
    req = req.json()
    for illusts_ids in req['body']['illusts']:
        id_list.append([illusts_ids,user_name]) 
        
    return id_list


# id -> artid
# get name for id mode
def get_user(id:int) -> str:   
    url = f'https://www.pixiv.net/artworks/{id}'

    req = requests.get(url)
    text = req.text
    # print(text)
    # find name
    obj = re.compile(r'"name":"(?P<name>.*?)"')
    user_name = obj.finditer(text)

    # get name
    for it in user_name:
        name =  it.group('name')
    
    # del非法字符
    name = name_replace(name)
    return name    
    
def main():
    os.system('cls')
    print(banner) 
    cfg = config_pixiv()
    AllInOneDir = cfg['path']['AllInOnePath']
    print('0:Pixiv_id mode\n1:Search mode\n2:Ranking mode\n3:User illusts\n4:Premium search(Need premium)')
    mode = int(input('Mode:'))
    print(f"Mode:{mode}".center(50,'='))
    if mode == 0: #id mode       
        dl_img(int(input('Pixiv_id:')),cfg,AllInOneDir=AllInOneDir)
    elif mode > 10000:
        dl_img(mode,cfg,AllInOneDir=AllInOneDir)
    elif mode == 1: #search mode       
        search = input("Search:")
        print('0:All\n1:Safe\n2:R18(login)')
        mode_num = int(input('mode:'))
        id_list , search_name = pixiv_search(search,cfg,mode=mode_num)
        dl_img(id_list,cfg,search_name,AllInOneDir=AllInOneDir)
    elif mode == 2: #ranking mode?
        # ['daily','weekly','monthly','rookie','original','female','daily_r18','male']
        page = int(input('Page:'))
        print('0:daily\n1:weekly\n2:monthly\n3:rookie\n4:original\n5:for female\n6:r18(login)\n7:for male')
        ranking_num = int(input('ranking_mode:'))
        if ranking_num == 6:
            try:
                print('0:daily_r18\n1:weekly_r18\n2:male_r18\n3:female_r18')
                r18mode = int(input("R18_mode:"))
                id_name_list , mode_ranking = ranking(page,cfg,mode_num=ranking_num,r18mode=r18mode)
                # print(mode_ranking)
                dl_img(id_name_list,cfg,ranking=mode_ranking,r18mode=True,AllInOneDir=AllInOneDir)
            except JSONDecodeError:
                exit('未登錄 . . .')             
        else:
            id_name_list , mode_ranking = ranking(page,cfg,mode_num=ranking_num)
            # print(id_name_list)
            # with ThreadPoolExecutor(30) as th:
            #     for ids in id_name_list:
            #         th.submit(dl_img,id=ids[0],cfg=cfg,ranking=mode_ranking,AllInOneDir=AllInOneDir)     
            dl_img(id_name_list,cfg,ranking=mode_ranking,AllInOneDir=AllInOneDir)
    elif mode == 3: #get_user_illusts
        user_id = int(input('user_id:'))
        id_list = get_user_illusts(user_id,cfg)
        dl_img(id_list,cfg,AllInOneDir=AllInOneDir)
    elif mode == 4: #premium_search
        search = input("Search:")
        print('0:All popular\n1:Popula for male\n2:Popula for female')
        order_num = int(input('order:'))
        print('0:r18 & safe\n1:safe\n2:R18')
        mode_4_num = int(input('mode:'))
        pages = int(input('pages:'))
        id_list , search_name = premium_search(search,order_num,mode_4_num,pages,cfg)
        dl_img(id_list,cfg,search_name,AllInOneDir=AllInOneDir)
        
    # cfg = config_pixiv()
    # print(cfg['login']['cookie'])
    
    # id_list , search_name = pixiv_search('甘雨',cfg)
    # print(name)
    # print(id_list)
    # name = get_user(id_list)
    # mark_dir(name)
    
    # dl_img(id_list,cfg,search_name)
    
    # print(pixiv_get())
    
if __name__ == '__main__': 
    try:
        main()
    except KeyboardInterrupt:
        exit('\nKeyboardInterrupt exit. . .')
